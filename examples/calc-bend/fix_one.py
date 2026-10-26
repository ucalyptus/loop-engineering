"""Deterministic stand-in for an agent, so the Bend loop runs offline.

Reads LOOP_TARGET and makes ONE change toward that check: it fixes the bug in calc.bend
and writes the proof in proof_<target>.bend. Each fix is anchored on the buggy text, so a
second run is a no-op. Swap `actor` for a real agent CLI (see loop.pi.toml).
"""

import os
from pathlib import Path

HEADER = (
    "import Base\nimport ./calc.bend as C\nimport ./laws_{op}.bend as Laws\n\n"
    "# PROOFS (agent-owned). Prove each law in laws_{op}.bend with `def Laws.<law>`.\n\n"
)

PROOFS = {
    "add": """def Laws.add_zero(a):
  {==}

def Laws.add_succ(a, b):
  {==}
""",
    "mul": """def Laws.mul_zero(a):
  {==}

def Laws.mul_succ(a, b):
  {==}
""",
    "double": """# add(1n+a, b) == 1n+add(a, b), by induction on b
def succ_left(+a: Nat, b: Nat) -> {C.add(1n+a, b) == 1n+C.add(a, b) : Nat}:
  match b:
    case 0n:
      {==}
    case 1n+q:
      %succ_left(a, q) : {1n+C.add(1n+a, q) == 1n+_ : Nat}
      {==}

# double(n) == add(n, n), by induction on n, using succ_left
def double_add(+n: Nat) -> {C.double(n) == C.add(n, n) : Nat}:
  match n:
    case 0n:
      {==}
    case 1n+p:
      %Equal.sym(Nat, C.add(1n+p, p), 1n+C.add(p, p), succ_left(p, p)) : {2n+C.double(p) == 1n+_ : Nat}
      %double_add(p) : {2n+C.double(p) == 2n+_ : Nat}
      {==}

def Laws.double_is_add(n):
  double_add(n)
""",
}

# target -> (buggy text, fixed text) in calc.bend
CODE = {
    "add": ("    case 1n+p:\n      add(a, p)\n", "    case 1n+p:\n      1n+add(a, p)\n"),
    "mul": ("    case 0n:\n      a\n    case 1n+p:\n      add(mul(a, p), a)",
            "    case 0n:\n      0n\n    case 1n+p:\n      add(mul(a, p), a)"),
    "double": ("      1n+double(p)\n", "      2n+double(p)\n"),
}

target = os.environ["LOOP_TARGET"]
if target not in CODE:
    print(f"{target}: no fix known")
    raise SystemExit(0)

src = Path("calc.bend")
text = src.read_text()
bad, good = CODE[target]
if bad in text:
    src.write_text(text.replace(bad, good, 1))

proof = Path(f"proof_{target}.bend")
body = HEADER.format(op=target) + PROOFS[target]
if proof.read_text() != body:
    proof.write_text(body)
print(f"{target}: fixed calc.bend and wrote {proof}")
