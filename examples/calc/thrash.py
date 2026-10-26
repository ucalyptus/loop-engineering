"""Over-correcting worker for the thrashing demo: every edit fixes `add` and breaks `mul`.

loopctl verifies each commit, reverts the regression, and halts once `max_regressions`
reverts pile up (exit 3), the way a governor stops an engine from hunting.
"""

from pathlib import Path

src = Path("calc.py")
text = src.read_text()
text = text.replace("def add(a, b):\n    return a - b", "def add(a, b):\n    return a + b", 1)
text = text.replace("def mul(a, b):\n    return a * b", "def mul(a, b):\n    return a * b + 1", 1)
src.write_text(text)
print("fixed add (and broke mul)")
