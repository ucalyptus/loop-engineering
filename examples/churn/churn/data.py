import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> list[dict]:
    """Rows of data/<name>.csv as dicts of strings."""
    with (ROOT / "data" / f"{name}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def labels(rows: list[dict]) -> list[int]:
    return [int(r["churned"]) for r in rows]
