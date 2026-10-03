"""Check: the data contract holds.

1. Raw CSVs match schema.json (columns, types, ranges, allowed values).
2. The feature pipeline turns every row into len(FEATURE_NAMES) finite floats.
Exit 0 if both hold. Loop sensor: the agent must not edit this file.
"""

import json
import math
import sys
from pathlib import Path

from churn.data import load
from churn.features import FEATURE_NAMES, encode

CASTS = {"int": int, "float": float, "str": str}


def raw_errors(name: str, spec: dict) -> list[str]:
    rows = load(name)
    if not rows or list(rows[0]) != list(spec):
        return [f"{name}.csv columns {list(rows[0]) if rows else []} != {list(spec)}"]
    errors = []
    for i, row in enumerate(rows):
        for col, rule in spec.items():
            try:
                value = CASTS[rule["type"]](row[col])
            except ValueError:
                errors.append(f"{name}.csv row {i}: {col}={row[col]!r} is not {rule['type']}")
                continue
            if "allowed" in rule and value not in rule["allowed"]:
                errors.append(f"{name}.csv row {i}: {col}={value!r} not in {rule['allowed']}")
            if "min" in rule and not rule["min"] <= value <= rule["max"]:
                errors.append(f"{name}.csv row {i}: {col}={value} outside [{rule['min']}, {rule['max']}]")
    return errors


def feature_errors(name: str) -> list[str]:
    errors = []
    for i, row in enumerate(load(name)):
        x = encode(row)
        if len(x) != len(FEATURE_NAMES):
            errors.append(f"{name} row {i}: {len(x)} features, FEATURE_NAMES has {len(FEATURE_NAMES)}")
        for fname, v in zip(FEATURE_NAMES, x):
            if not isinstance(v, float) or not math.isfinite(v):
                errors.append(f"{name} row {i}: feature {fname!r} = {v!r} is not a finite float")
        if errors:
            break  # one bad row explains the pipeline bug
    return errors


if __name__ == "__main__":
    spec = json.loads((Path(__file__).parent / "schema.json").read_text())["columns"]
    errors = [e for name in ("train", "holdout") for e in raw_errors(name, spec) + feature_errors(name)]
    for e in errors[:10]:
        print(e)
    print("schema: OK" if not errors else f"schema: {len(errors)} problem(s)")
    sys.exit(1 if errors else 0)
