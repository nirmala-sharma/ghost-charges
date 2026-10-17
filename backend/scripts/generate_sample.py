"""Generate a realistic synthetic bank statement for demos.

Usage: python scripts/generate_sample.py > sample_data/sample_transactions.csv
"""

import csv
import random
import sys
from datetime import date, timedelta

random.seed(42)
START, END = date(2025, 8, 1), date(2026, 9, 30)
rows: list[tuple[date, str, float]] = []


def monthly(day, desc, amount, until=END):
    y, m = START.year, START.month
    while (d := date(y, m, min(day, 28))) <= until:
        rows.append((d, desc(d), -amount(d)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# Recurring subscriptions
monthly(15, lambda d: f"NETFLIX.COM {random.randint(1000, 9999)} CA",
        lambda d: 15.49 if d < date(2026, 6, 1) else 17.99)  # price increase
monthly(3, lambda d: f"SPOTIFY USA #{random.randint(10000, 99999)}", lambda d: 10.99)
monthly(1, lambda d: "POS PLANET FITNESS", lambda d: 24.99)
monthly(20, lambda d: "APPLE.COM/BILL ICLOUD", lambda d: 2.99)
monthly(10, lambda d: "ADOBE *CREATIVE CLOUD", lambda d: 54.99, until=date(2026, 5, 31))  # cancelled
monthly(25, lambda d: "COMCAST XFINITY INTERNET", lambda d: 79.99 + random.choice([0, 0, 0, 2.15]))
monthly(5, lambda d: "ACH GEICO AUTO INSURANCE", lambda d: 112.40)
for d in (date(2025, 9, 12), date(2026, 9, 12)):
    rows.append((d, "AMAZON PRIME*MEMBERSHIP", -139.00))  # yearly

# Weekly habit (recurring but not a subscription - detector should still flag it as weekly)
d = date(2025, 8, 4)
while d <= END:
    rows.append((d, "SQ *BLUE BOTTLE COFFEE", -6.50))
    d += timedelta(days=7)

# Random one-off spending (noise)
groceries = ["WHOLE FOODS MARKET", "TRADER JOE'S #552", "SAFEWAY STORE 1234", "COSTCO WHSE #0423"]
misc = ["UBER TRIP", "DOORDASH*CHIPOTLE", "SHELL OIL 5741", "TARGET T-1123",
        "AMAZON MKTPLACE PMTS", "CVS PHARMACY", "BEST BUY 00012", "STARBUCKS STORE 1150"]
d = START
while d <= END:
    for _ in range(random.randint(0, 2)):
        pool = groceries if random.random() < 0.4 else misc
        rows.append((d, random.choice(pool), -round(random.uniform(8, 160), 2)))
    d += timedelta(days=1)

# Income (positive amounts - must be ignored)
monthly(1, lambda d: "PAYROLL DEPOSIT ACME CORP", lambda d: -3250.00)
monthly(15, lambda d: "PAYROLL DEPOSIT ACME CORP", lambda d: -3250.00)

rows.sort()
writer = csv.writer(sys.stdout, lineterminator="\n")
writer.writerow(["Date", "Description", "Amount"])
for d, desc, amt in rows:
    writer.writerow([d.isoformat(), desc, f"{amt:.2f}"])
