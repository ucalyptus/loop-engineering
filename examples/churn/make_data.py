"""Generate the synthetic churn dataset (deterministic). The CSVs are committed; rerun only to change them."""

import csv
import math
import random
from pathlib import Path

COLUMNS = ["customer_id", "tenure_months", "monthly_charges", "support_calls", "contract", "churned"]
CONTRACT_EFFECT = {"month": 1.4, "year": -0.4, "two_year": -1.8}


def row(rng: random.Random, i: int) -> list:
    tenure = rng.randint(0, 72)
    charges = round(rng.uniform(20, 120), 2)
    calls = min(10, int(rng.expovariate(0.6)))
    contract = rng.choices(list(CONTRACT_EFFECT), weights=[0.5, 0.3, 0.2])[0]
    logit = -2.0 - 0.06 * tenure + 0.035 * charges + 0.8 * calls + CONTRACT_EFFECT[contract]
    churned = int(rng.random() < 1 / (1 + math.exp(-logit)))
    return [f"C{i:05d}", tenure, charges, calls, contract, churned]


def write(path: Path, rows: list[list]) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)


if __name__ == "__main__":
    rng = random.Random(7)
    here = Path(__file__).parent
    write(here / "data" / "train.csv", [row(rng, i) for i in range(2000)])
    write(here / "data" / "holdout.csv", [row(rng, i) for i in range(2000, 2600)])
