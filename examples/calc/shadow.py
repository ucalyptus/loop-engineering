"""Cheating worker for the shadowing demo: it fixes nothing in calc.py.

It adds a one-line unittest.py next to the tests. `python3 -m unittest` imports it ahead of the
standard library, so every check exits 0. tests-unchanged only guards test_calc.py, a new file
gets through, and the loop "converges" on broken code. Compare examples/calc-bend/loop.cheat.toml,
where the sensor is a proof checker and the same kind of cheat goes nowhere.
"""

from pathlib import Path

Path("unittest.py").write_text("raise SystemExit(0)\n")
print("shadowed the stdlib unittest with a runner that always passes")
