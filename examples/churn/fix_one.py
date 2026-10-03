"""Deterministic stand-in for an agent, so the loop runs offline.

Reads LOOP_TARGET and makes ONE convergent edit toward that check. Each fix is anchored on
the exact buggy text, so a second run is a no-op. Swap `actor` for a real agent CLI.
"""

import os
import sys
from pathlib import Path

ONE_HOT_NAMES = 'FEATURE_NAMES = NUMERIC + [f"contract={c}" for c in CONTRACTS]'
ONE_HOT_ENCODE = (
    '    contract = [1.0 if row["contract"] == c else 0.0 for c in CONTRACTS]\n'
    "    return numeric + contract"
)

# target -> ordered fixes; each fix is (file, [(buggy text, fixed text), ...]) and is ONE change.
# The first fix whose buggy text is still present gets applied.
FIXES = {
    "schema": [
        ("churn/features.py", [
            ('FEATURE_NAMES = NUMERIC + ["contract"]', ONE_HOT_NAMES),
            ('    return numeric + [row["contract"]]', ONE_HOT_ENCODE),
        ]),
    ],
    "quality": [
        ("churn/model.py", [(
            '    return sigmoid(sum(w * v for w, v in zip(model["weights"], x)) + model["bias"])',
            '    xs = scale(x, model["scaler"])\n'
            '    return sigmoid(sum(w * v for w, v in zip(model["weights"], xs)) + model["bias"])',
        )]),
        ("churn/features.py", [(
            'NUMERIC = ["tenure_months", "monthly_charges"]',
            'NUMERIC = ["tenure_months", "monthly_charges", "support_calls"]',
        )]),
    ],
}


def write_model_card() -> None:
    sys.path.insert(0, os.getcwd())
    from churn.features import FEATURE_NAMES

    features = "\n".join(f"- `{name}`" for name in FEATURE_NAMES)
    Path("MODEL_CARD.md").write_text(f"""# Churn model

## Intended use
Rank current customers by risk of cancelling so the retention team can call the riskiest first.
Not for pricing or credit decisions.

## Training data
`data/train.csv`: 2,000 synthetic customers. Validated against `schema.json` before training.

## Features
{features}

## Evaluation
Holdout AUC on `data/holdout.csv` (600 customers); release bar is 0.85 (`eval.py --min-auc 0.85`).

## Limitations
Synthetic data. No fairness, calibration or drift analysis yet.
""")


def main() -> None:
    target = os.environ["LOOP_TARGET"]
    if target == "model-card":
        write_model_card()
        print("wrote MODEL_CARD.md")
        return
    for path, edits in FIXES.get(target, []):
        p = Path(path)
        text = p.read_text()
        if any(bad in text for bad, _ in edits):
            for bad, good in edits:
                text = text.replace(bad, good, 1)
            p.write_text(text)
            print(f"{target}: fixed {path}")
            return
    print(f"{target}: no known fix left")


if __name__ == "__main__":
    main()
