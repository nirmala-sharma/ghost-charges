"""Core subscription detection logic.

Pure functions with no web framework dependencies, so they are easy to unit test.

Algorithm:
1. Parse CSV rows into Transactions (flexible column names, several date formats).
2. Normalize each description into a merchant key ("NETFLIX.COM 8829#" -> "netflix").
3. Group debits by merchant.
4. For each group, check that the gaps between charges match a known cadence
   (weekly / monthly / quarterly / yearly) and that the amounts are stable.
5. Score confidence and project the next charge date.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d-%m-%Y", "%Y/%m/%d")

DATE_COLUMNS = ("date", "transaction date", "posted date", "posting date")
DESC_COLUMNS = ("description", "merchant", "name", "payee", "details", "memo")
AMOUNT_COLUMNS = ("amount", "debit", "value", "transaction amount")

# Tokens that banks prepend/append and that carry no merchant identity.
NOISE_TOKENS = {
    "pos", "ach", "debit", "credit", "card", "purchase", "payment", "recurring",
    "autopay", "online", "web", "www", "com", "net", "inc", "llc", "ltd", "co",
    "visa", "mastercard", "mc", "checkcard", "sq", "tst", "paypal", "the",
    # Indian bank transfer rails and markers (UPI/DR/123/NETFLIX/...)
    "upi", "neft", "imps", "rtgs", "nach", "ecs", "si", "dr", "cr", "txn", "ref", "mandate", "to",
    "subscription",
}

# (name, expected days between charges, tolerance in days, monthly multiplier)
CADENCES = (
    ("weekly", 7, 2, 52 / 12),
    ("biweekly", 14, 3, 26 / 12),
    ("monthly", 30.44, 5, 1.0),
    ("quarterly", 91.3, 10, 1 / 3),
    ("yearly", 365.25, 20, 1 / 12),
)

AMOUNT_TOLERANCE = 0.15  # charges may vary up to 15% from the median (taxes, FX, price bumps)


class CsvFormatError(ValueError):
    """Raised when the uploaded CSV cannot be interpreted."""


@dataclass(frozen=True)
class Transaction:
    date: date
    description: str
    amount: float  # positive = money spent


@dataclass(frozen=True)
class Subscription:
    merchant: str
    display_name: str
    cadence: str
    average_amount: float
    last_amount: float
    monthly_cost: float
    annual_cost: float
    occurrences: int
    first_charge: date
    last_charge: date
    next_expected: date
    confidence: float
    price_changed: bool
    likely_cancelled: bool


# ---------------------------------------------------------------- parsing

def _parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise CsvFormatError(f"Unrecognized date format: {raw!r}")


def _parse_amount(raw: str) -> float:
    cleaned = raw.strip().replace("$", "").replace(",", "").replace("₹", "").replace("€", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):  # accounting style negative
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError as exc:
        raise CsvFormatError(f"Unrecognized amount: {raw!r}") from exc


def _find_column(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    lookup = {h.strip().lower(): h for h in headers}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None


def parse_csv(content: str) -> list[Transaction]:
    """Parse bank-statement CSV text into transactions representing money spent."""
    reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
    headers = reader.fieldnames or []

    date_col = _find_column(headers, DATE_COLUMNS)
    desc_col = _find_column(headers, DESC_COLUMNS)
    amount_col = _find_column(headers, AMOUNT_COLUMNS)
    missing = [
        name for name, col in (("date", date_col), ("description", desc_col), ("amount", amount_col))
        if col is None
    ]
    if missing:
        raise CsvFormatError(
            f"Missing required column(s): {', '.join(missing)}. Found: {', '.join(headers) or 'none'}"
        )

    raw_rows: list[tuple[date, str, float]] = []
    for line_no, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue  # skip blank lines
        try:
            raw_rows.append((
                _parse_date(row[date_col] or ""),
                (row[desc_col] or "").strip(),
                _parse_amount(row[amount_col] or ""),
            ))
        except CsvFormatError as exc:
            raise CsvFormatError(f"Line {line_no}: {exc}") from exc

    # Banks disagree on sign. If any amount is negative, negatives are spending and
    # positives are deposits; otherwise every row is spending.
    has_negative = any(amount < 0 for _, _, amount in raw_rows)
    return [
        Transaction(d, desc, abs(amount))
        for d, desc, amount in raw_rows
        if amount != 0 and (amount < 0 or not has_negative)
    ]


# ---------------------------------------------------------------- normalization

def normalize_merchant(description: str) -> str:
    """Reduce a noisy bank description to a stable merchant key.

    "POS NETFLIX.COM 866-579-7172 CA" -> "netflix"
    "SPOTIFY USA #12345"              -> "spotify usa"
    """
    text = description.lower()
    text = re.sub(r"@\w+", " ", text)  # UPI handles like netflix@hdfc
    text = re.sub(r"[*#]+\s*\w*\d\w*", " ", text)  # reference ids like *A1B2 or #1234
    text = re.sub(r"[^a-z\s]", " ", text)  # drop digits and punctuation
    tokens: list[str] = []
    for t in text.split():
        if t not in NOISE_TOKENS and len(t) > 1 and t not in tokens:  # UPI repeats the payee
            tokens.append(t)
    # Drop trailing US state codes ("ca", "ny") that some banks append.
    if len(tokens) > 1 and len(tokens[-1]) == 2:
        tokens = tokens[:-1]
    return " ".join(tokens[:2]) or description.strip().lower()


def _display_name(descriptions: list[str], merchant_key: str) -> str:
    return merchant_key.title() if merchant_key else descriptions[0]


# ---------------------------------------------------------------- detection

def _match_cadence(intervals: list[int]) -> tuple[str, float, float] | None:
    """Return (name, monthly_multiplier, regularity 0..1) for the best-fitting cadence."""
    typical = median(intervals)
    for name, expected, tolerance, multiplier in CADENCES:
        if abs(typical - expected) <= tolerance:
            on_schedule = sum(1 for i in intervals if abs(i - expected) <= tolerance * 1.5)
            regularity = on_schedule / len(intervals)
            if regularity >= 0.6:
                return name, multiplier, regularity
    return None


def _price_changed(amounts: list[float]) -> bool:
    """True if the latest charge differs from the usual earlier price by more than 5%."""
    usual = median(amounts[:-1])
    return abs(amounts[-1] - usual) > usual * 0.05


def _analyze_group(merchant: str, txns: list[Transaction], as_of: date) -> Subscription | None:
    txns = sorted(txns, key=lambda t: t.date)
    # Collapse same-day duplicates (e.g. pending + posted).
    deduped: list[Transaction] = []
    for t in txns:
        if deduped and deduped[-1].date == t.date and abs(deduped[-1].amount - t.amount) < 0.01:
            continue
        deduped.append(t)
    txns = deduped

    if len(txns) < 2:
        return None

    intervals = [(b.date - a.date).days for a, b in zip(txns, txns[1:])]
    if any(i == 0 for i in intervals):
        return None

    cadence = _match_cadence(intervals)
    if cadence is None:
        return None
    cadence_name, monthly_multiplier, regularity = cadence

    # Two charges is only convincing for long cadences; short ones need 3+.
    if len(txns) < 3 and cadence_name not in ("quarterly", "yearly"):
        return None

    amounts = [t.amount for t in txns]
    typical_amount = median(amounts)
    stable = [a for a in amounts if abs(a - typical_amount) <= typical_amount * AMOUNT_TOLERANCE]
    amount_consistency = len(stable) / len(amounts)
    if amount_consistency < 0.6:
        return None

    last = txns[-1]
    expected_gap = next(c[1] for c in CADENCES if c[0] == cadence_name)
    next_expected = last.date + timedelta(days=round(expected_gap))
    tolerance = next(c[2] for c in CADENCES if c[0] == cadence_name)
    likely_cancelled = (as_of - next_expected).days > tolerance * 2

    # Confidence: blend regularity, amount stability and history length.
    history_score = min(len(txns) / 6, 1.0)
    confidence = round(0.45 * regularity + 0.35 * amount_consistency + 0.20 * history_score, 2)

    last_amount = round(last.amount, 2)
    monthly_cost = round(last_amount * monthly_multiplier, 2)
    return Subscription(
        merchant=merchant,
        display_name=_display_name([t.description for t in txns], merchant),
        cadence=cadence_name,
        average_amount=round(sum(amounts) / len(amounts), 2),
        last_amount=last_amount,
        monthly_cost=monthly_cost,
        annual_cost=round(monthly_cost * 12, 2),
        occurrences=len(txns),
        first_charge=txns[0].date,
        last_charge=last.date,
        next_expected=next_expected,
        confidence=confidence,
        price_changed=_price_changed(amounts),
        likely_cancelled=likely_cancelled,
    )


def detect_subscriptions(transactions: list[Transaction], as_of: date | None = None) -> list[Subscription]:
    """Find recurring charges, sorted by monthly cost (highest first)."""
    if not transactions:
        return []
    as_of = as_of or max(t.date for t in transactions)

    groups: dict[str, list[Transaction]] = {}
    for t in transactions:
        groups.setdefault(normalize_merchant(t.description), []).append(t)

    results = [
        sub for merchant, txns in groups.items()
        if (sub := _analyze_group(merchant, txns, as_of)) is not None
    ]
    return sorted(results, key=lambda s: s.monthly_cost, reverse=True)
