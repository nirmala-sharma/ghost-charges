from datetime import date

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from app.detector import Transaction, detect_subscriptions
from app.main import app
from app.pdf_parser import PdfParseError, PdfPasswordError, parse_pdf, parse_statement_text


def make_pdf(pages: list[list[str]], password: str | None = None) -> bytes:
    """Render lines of monospaced text into a PDF, one list of lines per page."""
    pdf = FPDF()
    if password:
        pdf.set_encryption(owner_password="owner", user_password=password)
    pdf.set_font("Courier", size=8)
    for lines in pages:
        pdf.add_page()
        for line in lines:
            pdf.cell(0, 4, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# Realistic layouts, including the clutter real statements have.

US_STATEMENT = [
    [
        "FIRST NATIONAL BANK                         Customer Service: 1-800-555-0199",
        "JANE DOE",
        "1234 MAIN STREET APT 5",
        "SPRINGFIELD, IL 62704",
        "Account Number: 000123456789          Statement Period: 01/01/2026 - 03/31/2026",
        "",
        "TRANSACTION DETAIL",
        "DATE   DESCRIPTION                              AMOUNT        BALANCE",
        "       Beginning Balance                                     5,000.00",
        "01/03  SPOTIFY USA #48213                       -10.99       4,989.01",
        "01/05  WHOLE FOODS MARKET #102                  -84.20       4,904.81",
        "01/15  PAYROLL DEPOSIT ACME CORP              3,250.00       8,154.81",
        "01/15  NETFLIX.COM 866-579-7172 CA              -15.49       8,139.32",
        "02/03  SPOTIFY USA #77120                       -10.99       8,128.33",
        "Page 1 of 2",
    ],
    [
        "FIRST NATIONAL BANK - Account 000123456789 (continued)",
        "DATE   DESCRIPTION                              AMOUNT        BALANCE",
        "02/15  NETFLIX.COM 866-579-7172 CA              -15.49       8,112.84",
        "02/20  SHELL OIL 5741                           -42.10       8,070.74",
        "03/03  SPOTIFY USA #10293                       -10.99       8,059.75",
        "03/15  NETFLIX.COM 866-579-7172 CA              -15.49       8,044.26",
        "       Ending Balance                                        8,044.26",
        "Total withdrawals                              -205.74",
        "Page 2 of 2   Member FDIC. Questions? Visit firstnational.example",
    ],
]

# HDFC-style: dd/mm/yy, ref no + value date columns, separate withdrawal/deposit columns
# (blank column means only one amount + balance appear), no Dr/Cr markers.
INDIAN_STATEMENT = [
    [
        "HDFC BANK LTD                                  Statement of account",
        "MR RAHUL SHARMA",
        "FLAT 12, MG ROAD, BENGALURU 560001",
        "Account No : 50100123456789    Cust ID : 87654321    Currency : INR",
        "IFSC : HDFC0001234   Statement From : 01/01/2026  To : 31/03/2026",
        "Date     Narration                         Chq./Ref.No.     Value Dt  Withdrawal  Deposit  Closing Balance",
        "Opening Balance                                                                          50,000.00",
        "05/01/26 UPI-NETFLIX-NETFLIX@HDFC          0000412345678901 05/01/26   649.00              49,351.00",
        "07/01/26 UPI-SWIGGY-SWIGGY@ICICI           0000412345678902 07/01/26   412.50              48,938.50",
        "10/01/26 NEFT CR-ACME TECH PVT LTD         N010261234567    10/01/26          85,000.00   1,33,938.50",
        "15/01/26 ACH D- HOTSTAR-SUBSCRIPTION       0000000000000015 15/01/26   299.00            1,33,639.50",
        "05/02/26 UPI-NETFLIX-NETFLIX@HDFC          0000412345678903 05/02/26   649.00            1,32,990.50",
        "15/02/26 ACH D- HOTSTAR-SUBSCRIPTION       0000000000000016 15/02/26   299.00            1,32,691.50",
        "21/02/26 UPI-ZOMATO-ZOMATO@HDFC            0000412345678904 21/02/26   289.00            1,32,402.50",
        "05/03/26 UPI-NETFLIX-NETFLIX@HDFC          0000412345678905 05/03/26   649.00            1,31,753.50",
        "15/03/26 ACH D- HOTSTAR-SUBSCRIPTION       0000000000000017 15/03/26   299.00            1,31,454.50",
        "STATEMENT SUMMARY : Closing Balance 1,31,454.50",
        "*This is a computer generated statement and does not require signature",
    ]
]

# SBI/ICICI-style: "15 Jan 2026" dates with value date, Dr/Cr markers on amounts.
DR_CR_STATEMENT = [
    [
        "STATE BANK OF INDIA   Account Statement   Branch: Andheri West",
        "Account Number 00000031234567890",
        "Txn Date      Value Date    Description                        Amount        Balance",
        "02 Jan 2026   02 Jan 2026   TO TRANSFER-UPI/DR/601234/SPOTIFY  119.00 Dr   20,000.00 Cr",
        "09 Jan 2026   09 Jan 2026   BY TRANSFER-UPI/CR/601299/MOM    5,000.00 Cr   25,000.00 Cr",
        "02 Feb 2026   02 Feb 2026   TO TRANSFER-UPI/DR/602234/SPOTIFY  119.00 Dr   24,881.00 Cr",
        "02 Mar 2026   02 Mar 2026   TO TRANSFER-UPI/DR/603234/SPOTIFY  119.00 Dr   24,762.00 Cr",
    ]
]


def test_us_statement_skips_clutter_and_income():
    txns = parse_pdf(make_pdf(US_STATEMENT))
    descriptions = [t.description for t in txns]
    assert len(txns) == 8  # 9 transaction rows minus 1 payroll deposit
    assert not any("PAYROLL" in d for d in descriptions)
    assert not any("Balance" in d or "Total" in d for d in descriptions)
    assert txns[0] == Transaction(date(2026, 1, 3), "SPOTIFY USA #48213", 10.99)


def test_us_statement_end_to_end_detection():
    subs = {s.merchant: s for s in detect_subscriptions(parse_pdf(make_pdf(US_STATEMENT)))}
    assert set(subs) == {"netflix", "spotify usa"}
    assert subs["netflix"].last_amount == 15.49


def test_indian_statement_uses_balance_to_find_debits():
    txns = parse_pdf(make_pdf(INDIAN_STATEMENT))
    assert len(txns) == 8  # 9 rows minus the NEFT salary credit
    assert txns[0].date == date(2026, 1, 5)  # dd/mm/yy, not May 1st
    assert txns[0].amount == 649.00
    assert all("ACME" not in t.description for t in txns)
    # value date and reference number are not left in the amount
    assert {t.amount for t in txns} == {649.0, 412.5, 299.0, 289.0}


def test_indian_statement_end_to_end_detection():
    subs = {s.merchant: s for s in detect_subscriptions(parse_pdf(make_pdf(INDIAN_STATEMENT)))}
    assert set(subs) == {"netflix", "hotstar"}
    assert subs["netflix"].cadence == "monthly"


def test_dr_cr_markers():
    txns = parse_pdf(make_pdf(DR_CR_STATEMENT))
    assert [t.amount for t in txns] == [119.0, 119.0, 119.0]
    assert txns[0].date == date(2026, 1, 2)
    assert txns[0].description.startswith("TO TRANSFER-UPI/DR")


def test_year_rollover_without_years_on_rows():
    text = "Statement period Dec 1, 2025 to Feb 28, 2026\nDec 20 GYM 30.00\nJan 20 GYM 30.00\nFeb 20 GYM 30.00\n"
    assert [t.date for t in parse_statement_text(text)] == [
        date(2025, 12, 20), date(2026, 1, 20), date(2026, 2, 20)
    ]


def test_ambiguous_numeric_dates_resolved_by_evidence():
    mdy = parse_statement_text("2026\n01/02 A 1.00\n01/25 B 1.00\n")
    assert mdy[0].date == date(2026, 1, 2)
    dmy = parse_statement_text("2026\n01/02 A 1.00\n25/01 B 1.00\n")
    assert dmy[0].date == date(2026, 2, 1)


def test_password_protected_pdf():
    data = make_pdf(US_STATEMENT, password="secret")
    with pytest.raises(PdfPasswordError, match="password-protected"):
        parse_pdf(data)
    with pytest.raises(PdfPasswordError, match="Incorrect"):
        parse_pdf(data, password="wrong")
    assert len(parse_pdf(data, password="secret")) == 8


def test_pdf_without_transactions():
    with pytest.raises(PdfParseError, match="Couldn't find any transactions"):
        parse_pdf(make_pdf([["Dear customer, thank you for banking with us."]]))


def test_pdf_with_no_text_layer():
    with pytest.raises(PdfParseError, match="scanned"):
        parse_pdf(make_pdf([[]]))


# ---------------------------------------------------------------- API

client = TestClient(app)


def test_api_accepts_pdf():
    res = client.post("/api/analyze", files={"file": ("statement.pdf", make_pdf(INDIAN_STATEMENT), "application/pdf")})
    assert res.status_code == 200
    assert res.json()["summary"]["subscriptions_found"] == 2


def test_api_password_flow():
    data = make_pdf(US_STATEMENT, password="secret")
    res = client.post("/api/analyze", files={"file": ("s.pdf", data, "application/pdf")})
    assert res.status_code == 401
    res = client.post("/api/analyze", files={"file": ("s.pdf", data, "application/pdf")}, data={"password": "secret"})
    assert res.status_code == 200
