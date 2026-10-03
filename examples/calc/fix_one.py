"""Deterministic stand-in for an LLM actor, so the loop can be demoed offline.

Reads LOOP_TARGET and applies one convergent edit ("calc.py contains X"), so
re-running it is a no-op. Swap `actor` in loop.toml for a real agent CLI.
"""

import os
from pathlib import Path

FIXES = {
    "add": ("def add(a, b):\n    return a - b", "def add(a, b):\n    return a + b"),
    "sub": ("    return a + b\n\n\ndef mul", "    return a - b\n\n\ndef mul"),
    "div": ("        return 0\n", "        raise ZeroDivisionError('division by zero')\n"),
}

target = os.environ["LOOP_TARGET"]
if target not in FIXES:
    print(f"{target}: no code change can fix this")
    raise SystemExit(0)
src = Path("calc.py")
text = src.read_text()
bad, good = FIXES[target]
if bad in text:
    src.write_text(text.replace(bad, good, 1))
    print(f"fixed {target}")
else:
    print(f"{target}: nothing to change")
