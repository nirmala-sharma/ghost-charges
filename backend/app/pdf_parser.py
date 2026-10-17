"""Extract transactions from bank-statement PDFs.

Bank PDFs are free-form: account details, addresses, headers, footers and promos sit
alongside the transaction table, and every bank lays the table out differently. Rather
than per-bank templates, this uses layout-agnostic heuristics:

1. Extract text line by line (pdfplumber keeps table rows on one line).
2. A transaction line starts with a date and ends with one to three money amounts.
   Everything else (account number, address, page headers...) is ignored.
3. Split the line into date | description | amount [| amount] [| balance].
4. Decide debit vs credit, in order of reliability:
   explicit Dr/Cr or minus sign -> change in running balance -> description keywords.
5. Resolve ambiguous dates (01/02 = Jan 2 or Feb 1?) using evidence from the whole
   statement, and fill in missing years from the statement text.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect

from .detector import Transaction

MONTHS = {
    m: i
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
         ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
         ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december")],
        start=1,
    )
    for m in names
}

# Dates at the start of a line, most specific first.
DATE_PATTERNS = [
    ("iso", re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})\b")),
    ("num", re.compile(r"^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")),
    ("dmon", re.compile(r"^(\d{1,2})[ -]([A-Za-z]{3,9})[ -,]*(\d{4}|\d{2}(?!\d))?\b")),
    ("mond", re.compile(r"^([A-Za-z]{3,9})\.? (\d{1,2})(?:,? (\d{4}))?\b")),
]

# A money amount: requires two decimals so reference numbers and dates are not mistaken
# for amounts. Supports 1,234.56 / 1,23,456.78 (Indian) / 1234.56 / ($12.00) / 12.00 Dr.
AMOUNT = (
    r"\(?-?\s?[$₹€£]?\s?(?:\d{1,3}(?:,\d{2,3})+|\d+)\.\d{2}\)?-?"
    r"(?:\s?(?:Cr|Dr|CR|DR|cr|dr)\.?)?"
)
TRAILING_AMOUNT = re.compile(rf"\s({AMOUNT})\s*$")
TRAILING_VALUE_DATE = re.compile(r"\s\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$|\s\d{1,2}[ -][A-Za-z]{3}[ -]\d{2,4}$")

OPENING_BALANCE = re.compile(
    r"(opening|beginning|previous|starting)\s+balance|balance\s+(brought\s+)?forward|\bb/f\b", re.I
)
SKIP_LINE = re.compile(
    r"(closing|ending|available|ledger)\s+balance|balance\s+carried|\bc/f\b|^\s*total\b|statement\s+period", re.I
)
CREDIT_WORDS = re.compile(
    r"\b(deposit|salary|payroll|refund|reversal|interest|cashback|credit|received|neft\s*cr|by\s+transfer)\b", re.I
)
CURRENCY_HINT_DMY = re.compile(r"₹|\bINR\b|\bRs\.?\s", re.I)


class PdfParseError(ValueError):
    """Raised when a PDF cannot be turned into transactions."""


class PdfPasswordError(PdfParseError):
    """Raised when a PDF is encrypted and the password is missing or wrong."""


@dataclass
class _RawRow:
    date_kind: str
    date_parts: tuple[str, str, str | None]
    description: str
    amounts: list[str]


# ---------------------------------------------------------------- text extraction

def extract_text(data: bytes, password: str | None = None) -> str:
    try:
        with pdfplumber.open(io.BytesIO(data), password=password or "") as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except PDFPasswordIncorrect as exc:
        raise _password_error(password) from exc
    except Exception as exc:  # pdfplumber wraps pdfminer errors in its own exception type
        if isinstance(exc.__cause__, PDFPasswordIncorrect) or "PDFPasswordIncorrect" in repr(exc):
            raise _password_error(password) from exc
        raise PdfParseError("Could not read this PDF. Is it a valid, unlocked bank statement?") from exc


def _password_error(password: str | None) -> PdfPasswordError:
    if password:
        return PdfPasswordError("Incorrect PDF password.")
    return PdfPasswordError("This PDF is password-protected. Enter the password to continue.")


# ---------------------------------------------------------------- amounts

def _parse_money(token: str) -> tuple[float, int | None]:
    """Return (absolute value, sign hint) where hint is -1 debit, +1 credit, None unknown."""
    t = token.strip()
    hint: int | None = None
    if re.search(r"dr\.?$", t, re.I):
        hint = -1
    elif re.search(r"cr\.?$", t, re.I):
        hint = 1
    t = re.sub(r"(?i)\s?(cr|dr)\.?$", "", t)
    if t.startswith("(") or t.startswith("-") or t.endswith("-"):
        hint = -1
    value = float(re.sub(r"[^\d.]", "", t))
    return value, hint


# ---------------------------------------------------------------- line parsing

def _match_date(line: str) -> tuple[str, tuple[str, str, str | None], int] | None:
    for kind, pattern in DATE_PATTERNS:
        m = pattern.match(line)
        if not m:
            continue
        a, b, c = m.group(1), m.group(2), m.group(3)
        if kind == "dmon" and b.lower() not in MONTHS:
            continue
        if kind == "mond" and a.lower() not in MONTHS:
            continue
        return kind, (a, b, c), m.end()
    return None


def _split_line(line: str) -> _RawRow | None:
    line = line.strip()
    matched = _match_date(line)
    if matched is None:
        return None
    kind, parts, end = matched
    rest = line[end:]

    amounts: list[str] = []
    while len(amounts) < 3 and (m := TRAILING_AMOUNT.search(rest)):
        amounts.insert(0, m.group(1))
        rest = rest[: m.start()]
    if not amounts:
        return None

    # Many banks print a value date right after the transaction date; drop it.
    description = rest.strip(" |-:")
    if (second := _match_date(description)) is not None:
        description = description[second[2]:].strip(" |-:")
    description = TRAILING_VALUE_DATE.sub("", description).strip(" |-:")
    if not description:
        return None
    return _RawRow(kind, parts, re.sub(r"\s{2,}", " ", description), amounts)


# ---------------------------------------------------------------- date resolution

def _numeric_order(rows: list[_RawRow], text: str) -> str:
    """Decide whether numeric dates are day-first ("dmy") or month-first ("mdy")."""
    nums = [(int(r.date_parts[0]), int(r.date_parts[1])) for r in rows if r.date_kind == "num"]
    if any(a > 12 for a, _ in nums):
        return "dmy"
    if any(b > 12 for _, b in nums):
        return "mdy"
    return "dmy" if CURRENCY_HINT_DMY.search(text) else "mdy"


def _to_ymd(row: _RawRow, order: str) -> tuple[int | None, int, int]:
    a, b, c = row.date_parts
    if row.date_kind == "iso":
        return int(a), int(b), int(c)
    if row.date_kind == "num":
        day, month = (int(a), int(b)) if order == "dmy" else (int(b), int(a))
    elif row.date_kind == "dmon":
        day, month = int(a), MONTHS[b.lower()]
    else:  # mond
        day, month = int(b), MONTHS[a.lower()]
    year = None
    if c:
        year = int(c) + (2000 if len(c) == 2 else 0)
    return year, month, day


def _statement_start_year(text: str) -> int:
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    return min(years) if years else date.today().year


# ---------------------------------------------------------------- main entry points

def parse_statement_text(text: str) -> list[Transaction]:
    """Parse extracted statement text into transactions representing money spent."""
    rows: list[_RawRow] = []
    opening_balance: float | None = None
    for line in text.splitlines():
        if OPENING_BALANCE.search(line):
            m = TRAILING_AMOUNT.search(" " + line.strip())
            if m and opening_balance is None:
                opening_balance = _parse_money(m.group(1))[0]
            continue
        if SKIP_LINE.search(line):
            continue
        if (row := _split_line(line)) is not None:
            rows.append(row)

    if not rows:
        return []

    order = _numeric_order(rows, text)
    year = _statement_start_year(text)
    prev_month: int | None = None
    prev_balance = opening_balance
    spending: list[Transaction] = []

    for row in rows:
        explicit_year, month, day = _to_ymd(row, order)
        if explicit_year is not None:
            year = explicit_year
        elif prev_month is not None and month < prev_month - 6:
            year += 1  # statement crosses a year boundary (Dec -> Jan)
        prev_month = month
        try:
            txn_date = date(year, month, day)
        except ValueError:
            continue

        values = [_parse_money(a) for a in row.amounts]
        amount, hint = values[0]
        balance: float | None = None
        if len(values) == 3:
            # withdrawal | deposit | balance, with the unused column printed as 0.00
            withdrawal, deposit = values[0][0], values[1][0]
            amount, hint = (withdrawal, -1) if withdrawal > 0 else (deposit, 1)
            balance = values[2][0]
        elif len(values) == 2:
            balance = values[1][0]

        sign = hint
        if sign is None and balance is not None and prev_balance is not None:
            if abs(prev_balance - amount - balance) < 0.011:
                sign = -1
            elif abs(prev_balance + amount - balance) < 0.011:
                sign = 1
        if sign is None:
            sign = 1 if CREDIT_WORDS.search(row.description) else -1
        if balance is not None:
            prev_balance = balance

        if sign < 0 and amount > 0:
            spending.append(Transaction(txn_date, row.description, amount))
    return spending


def parse_pdf(data: bytes, password: str | None = None) -> list[Transaction]:
    text = extract_text(data, password)
    if not text.strip():
        raise PdfParseError(
            "No text found in this PDF. It may be a scanned image; download the statement "
            "from online banking instead of scanning it."
        )
    transactions = parse_statement_text(text)
    if not transactions:
        raise PdfParseError(
            "Couldn't find any transactions in this PDF. Try exporting a CSV from your bank instead."
        )
    return transactions
