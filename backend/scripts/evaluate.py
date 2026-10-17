"""Measure detector accuracy against synthetic statements with known ground truth.

Each generated statement mixes:
  - true subscriptions (weekly/biweekly/monthly/quarterly/yearly) with realistic messiness:
    date jitter, skipped payments, price increases, cancellations, noisy descriptions
  - distractors that must NOT be flagged: variable-amount regulars (groceries, fuel),
    same-amount purchases at random intervals (coffee), and one-off duplicates

Reports precision, recall and F1 for detection, plus cadence accuracy, monthly-cost
error and cancellation-flag accuracy on the correctly detected subscriptions.

Usage: python -m scripts.evaluate [--statements 300] [--seed 7]
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from app.detector import Transaction, detect_subscriptions, normalize_merchant

START, END = date(2025, 1, 1), date(2026, 6, 30)

CADENCE_DAYS = {"weekly": 7, "biweekly": 14, "monthly": 30.44, "quarterly": 91.3, "yearly": 365.25}
MONTHLY_MULTIPLIER = {"weekly": 52 / 12, "biweekly": 26 / 12, "monthly": 1.0, "quarterly": 1 / 3, "yearly": 1 / 12}
CADENCE_WEIGHTS = {"weekly": 1, "biweekly": 1, "monthly": 6, "quarterly": 1, "yearly": 1}

SUB_MERCHANTS = [
    "NETFLIX", "SPOTIFY", "HULU", "DISNEY PLUS", "YOUTUBE PREMIUM", "AUDIBLE", "DROPBOX",
    "NOTION LABS", "GITHUB", "OPENTABLE", "PELOTON", "EQUINOX", "NYTIMES", "DUOLINGO",
    "CANVA", "GRAMMARLY", "MICROSOFT", "LINKEDIN PREMIUM", "PATREON", "HEADSPACE",
    "STATE FARM", "VERIZON WIRELESS", "TMOBILE", "PG&E UTILITIES", "ADT SECURITY",
]
VARIABLE_MERCHANTS = ["WHOLE FOODS", "SAFEWAY", "SHELL OIL", "CHEVRON", "TARGET", "WALGREENS", "UBER", "LYFT"]
FIXED_PRICE_RANDOM = ["BLUE BOTTLE", "PHILZ COFFEE", "CHIPOTLE", "SUBWAY", "PARKING METER"]


@dataclass
class Truth:
    key: str
    cadence: str
    monthly_cost: float
    cancelled: bool


def noisy(name: str, rng: random.Random) -> str:
    """Decorate a merchant name the way banks do."""
    style = rng.randint(0, 3)
    if style == 0:
        return f"{name} #{rng.randint(1000, 99999)}"
    if style == 1:
        return f"POS {name}"
    if style == 2:
        return f"{name}.COM {rng.randint(100, 999)}-{rng.randint(1000, 9999)} CA"
    return f"ACH {name} PAYMENT"


def make_subscription(name: str, rng: random.Random) -> tuple[list[Transaction], Truth]:
    cadence = rng.choices(list(CADENCE_WEIGHTS), weights=list(CADENCE_WEIGHTS.values()))[0]
    gap = CADENCE_DAYS[cadence]
    amount = round(rng.uniform(3, 150), 2)
    price_bump_at = rng.random() < 0.25
    cancel = rng.random() < 0.2

    total_days = (END - START).days
    first = START + timedelta(days=rng.randint(0, int(min(gap, total_days / 3))))
    stop = END - timedelta(days=rng.randint(90, 200)) if cancel else END

    txns: list[Transaction] = []
    n = 0
    while True:
        due = first + timedelta(days=round(n * gap))
        if due > stop:
            break
        n += 1
        if rng.random() < 0.05:  # occasional skipped payment
            continue
        jitter = timedelta(days=rng.choice([0, 0, 0, 1, -1, 2, 3]))  # weekends, posting delay
        price = amount * 1.2 if price_bump_at and due > START + (END - START) * 0.7 else amount
        txns.append(Transaction(due + jitter, noisy(name, rng), round(price, 2)))

    final_amount = txns[-1].amount if txns else amount
    truth = Truth(
        key=normalize_merchant(name),
        cadence=cadence,
        monthly_cost=round(final_amount * MONTHLY_MULTIPLIER[cadence], 2),
        cancelled=cancel,
    )
    return txns, truth


def make_distractors(rng: random.Random) -> list[Transaction]:
    txns: list[Transaction] = []
    total_days = (END - START).days
    for name in rng.sample(VARIABLE_MERCHANTS, 4):  # frequent, variable amounts
        for _ in range(rng.randint(10, 40)):
            d = START + timedelta(days=rng.randint(0, total_days))
            txns.append(Transaction(d, noisy(name, rng), round(rng.uniform(8, 180), 2)))
    for name in rng.sample(FIXED_PRICE_RANDOM, 2):  # same price, random timing
        price = round(rng.uniform(4, 15), 2)
        for _ in range(rng.randint(4, 25)):
            d = START + timedelta(days=rng.randint(0, total_days))
            txns.append(Transaction(d, noisy(name, rng), price))
    return txns


def generate_statement(rng: random.Random) -> tuple[list[Transaction], dict[str, Truth]]:
    txns = make_distractors(rng)
    truths: dict[str, Truth] = {}
    for name in rng.sample(SUB_MERCHANTS, rng.randint(3, 10)):
        sub_txns, truth = make_subscription(name, rng)
        min_needed = 2 if truth.cadence in ("quarterly", "yearly") else 3
        if len(sub_txns) < min_needed:
            continue  # not enough history to be detectable by anyone; don't count it
        txns.extend(sub_txns)
        truths[truth.key] = truth
    return txns, truths


def evaluate(statements: int, seed: int) -> None:
    rng = random.Random(seed)
    tp = fp = fn = 0
    cadence_right = cancel_right = 0
    cost_errors: list[float] = []
    false_positives: Counter[str] = Counter()
    misses: Counter[str] = Counter()

    for _ in range(statements):
        txns, truths = generate_statement(rng)
        found = {s.merchant: s for s in detect_subscriptions(txns, as_of=END)}

        for key, sub in found.items():
            truth = truths.get(key)
            if truth is None:
                fp += 1
                false_positives[key] += 1
                continue
            tp += 1
            cadence_right += sub.cadence == truth.cadence
            cancel_right += sub.likely_cancelled == truth.cancelled
            cost_errors.append(abs(sub.monthly_cost - truth.monthly_cost) / truth.monthly_cost)
        for key, truth in truths.items():
            if key not in found:
                fn += 1
                misses[truth.cadence] += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    print(f"Evaluated {statements} synthetic statements (seed={seed})\n")
    print("Detection")
    print(f"  True positives : {tp}")
    print(f"  False positives: {fp}")
    print(f"  False negatives: {fn}")
    print(f"  Precision      : {precision:.1%}")
    print(f"  Recall         : {recall:.1%}")
    print(f"  F1 score       : {f1:.1%}\n")
    print("On correctly detected subscriptions")
    print(f"  Cadence accuracy        : {cadence_right / tp:.1%}")
    print(f"  Cancelled-flag accuracy : {cancel_right / tp:.1%}")
    print(f"  Mean monthly-cost error : {sum(cost_errors) / len(cost_errors):.2%}")
    if false_positives:
        print(f"\nMost common false positives: {false_positives.most_common(5)}")
    if misses:
        print(f"Misses by cadence: {dict(misses)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--statements", type=int, default=300)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    evaluate(args.statements, args.seed)
