from datetime import date, timedelta

import pytest

from app.detector import (
    CsvFormatError,
    Transaction,
    detect_subscriptions,
    normalize_merchant,
    parse_csv,
)


def monthly(desc: str, amount: float, count: int, start: date = date(2026, 1, 15)) -> list[Transaction]:
    return [Transaction(start + timedelta(days=30 * i), desc, amount) for i in range(count)]


# ---------------------------------------------------------------- normalize_merchant

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NETFLIX.COM 8829 CA", "netflix"),
        ("POS NETFLIX.COM", "netflix"),
        ("SPOTIFY USA #12345", "spotify usa"),
        ("SPOTIFY USA #98765", "spotify usa"),
        ("ADOBE *CREATIVE CLOUD", "adobe creative"),
    ],
)
def test_normalize_merchant_strips_noise(raw, expected):
    assert normalize_merchant(raw) == expected


# ---------------------------------------------------------------- parse_csv

def test_parse_csv_keeps_only_spending_when_signs_mixed():
    content = "Date,Description,Amount\n2026-01-01,Netflix,-15.49\n2026-01-02,Salary,3000\n"
    txns = parse_csv(content)
    assert txns == [Transaction(date(2026, 1, 1), "Netflix", 15.49)]


def test_parse_csv_treats_all_positive_as_spending():
    content = "date,merchant,debit\n01/05/2026,Spotify,$10.99\n"
    assert parse_csv(content) == [Transaction(date(2026, 1, 5), "Spotify", 10.99)]


def test_parse_csv_handles_bom_blank_lines_and_accounting_negatives():
    content = "﻿Date,Description,Amount\n\n2026-01-01,Gym,(24.99)\n2026-01-02,Refund,5.00\n"
    assert parse_csv(content) == [Transaction(date(2026, 1, 1), "Gym", 24.99)]


def test_parse_csv_missing_columns():
    with pytest.raises(CsvFormatError, match="Missing required column"):
        parse_csv("foo,bar\n1,2\n")


def test_parse_csv_bad_date_reports_line():
    with pytest.raises(CsvFormatError, match="Line 2"):
        parse_csv("Date,Description,Amount\nnot-a-date,X,1\n")


# ---------------------------------------------------------------- detect_subscriptions

def test_detects_monthly_subscription():
    subs = detect_subscriptions(monthly("NETFLIX.COM 1234", 15.49, 6))
    assert len(subs) == 1
    sub = subs[0]
    assert sub.merchant == "netflix"
    assert sub.cadence == "monthly"
    assert sub.monthly_cost == 15.49
    assert sub.annual_cost == pytest.approx(185.88)
    assert sub.occurrences == 6
    assert sub.confidence == 1.0
    assert sub.next_expected == sub.last_charge + timedelta(days=30)


def test_ignores_random_spending():
    txns = [
        Transaction(date(2026, 1, 1), "UBER TRIP", 12.0),
        Transaction(date(2026, 1, 9), "UBER TRIP", 31.0),
        Transaction(date(2026, 2, 27), "UBER TRIP", 8.5),
        Transaction(date(2026, 3, 3), "UBER TRIP", 44.0),
    ]
    assert detect_subscriptions(txns) == []


def test_requires_three_charges_for_monthly():
    assert detect_subscriptions(monthly("Spotify", 10.99, 2)) == []


def test_yearly_needs_only_two_charges():
    txns = [
        Transaction(date(2025, 3, 1), "AMAZON PRIME", 139.0),
        Transaction(date(2026, 3, 1), "AMAZON PRIME", 139.0),
    ]
    (sub,) = detect_subscriptions(txns)
    assert sub.cadence == "yearly"
    assert sub.monthly_cost == pytest.approx(11.58)


def test_weekly_cadence():
    txns = [Transaction(date(2026, 1, 1) + timedelta(weeks=i), "GYM CLASS", 20.0) for i in range(5)]
    (sub,) = detect_subscriptions(txns)
    assert sub.cadence == "weekly"
    assert sub.monthly_cost == pytest.approx(20 * 52 / 12, abs=0.01)


def test_flags_price_change():
    txns = monthly("NETFLIX", 15.49, 5) + monthly("NETFLIX", 17.99, 1, start=date(2026, 6, 14))
    (sub,) = detect_subscriptions(txns)
    assert sub.price_changed
    assert sub.last_amount == 17.99


def test_flags_likely_cancelled():
    txns = monthly("ADOBE", 54.99, 4)
    (sub,) = detect_subscriptions(txns, as_of=date(2026, 12, 1))
    assert sub.likely_cancelled


def test_rejects_wildly_varying_amounts():
    txns = [Transaction(date(2026, 1, 1) + timedelta(days=30 * i), "AMAZON", amt)
            for i, amt in enumerate([12, 89, 5, 230, 41])]
    assert detect_subscriptions(txns) == []


def test_dedupes_same_day_duplicates():
    txns = monthly("SPOTIFY", 10.99, 4)
    txns.append(Transaction(txns[0].date, "SPOTIFY", 10.99))
    (sub,) = detect_subscriptions(txns)
    assert sub.occurrences == 4


def test_sorted_by_monthly_cost_desc():
    txns = monthly("CHEAP", 2.99, 4) + monthly("PRICEY", 99.0, 4)
    assert [s.merchant for s in detect_subscriptions(txns)] == ["pricey", "cheap"]
