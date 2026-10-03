"""Check: MODEL_CARD.md exists, has the required sections, and names every model feature.

Catches docs drifting from the code: add a feature without documenting it and this fails.
Loop sensor: the agent must not edit this file.
"""

import sys
from pathlib import Path

from churn.features import FEATURE_NAMES

SECTIONS = ["## Intended use", "## Training data", "## Features", "## Evaluation", "## Limitations"]

if __name__ == "__main__":
    card = Path(__file__).parent / "MODEL_CARD.md"
    if not card.exists():
        sys.exit("model card: MODEL_CARD.md is missing")
    text = card.read_text()
    problems = [f"missing section {s!r}" for s in SECTIONS if s not in text]
    problems += [f"feature `{f}` is not documented" for f in FEATURE_NAMES if f"`{f}`" not in text]
    for p in problems:
        print(f"model card: {p}")
    print("model card: OK" if not problems else f"model card: {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
