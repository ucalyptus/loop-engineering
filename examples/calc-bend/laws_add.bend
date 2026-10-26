import Base
import ./calc.bend as C

# SPEC (human-owned, frozen by admission): add is addition.

law add_zero:
  for a: Nat
  {C.add(a, 0n) == a : Nat}

law add_succ:
  for a: Nat
  for b: Nat
  {C.add(a, 1n+b) == 1n+C.add(a, b) : Nat}
