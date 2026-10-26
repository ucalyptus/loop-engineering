import Base
import ./calc.bend as C

# SPEC (human-owned, frozen by admission): mul is repeated add.

law mul_zero:
  for a: Nat
  {C.mul(a, 0n) == 0n : Nat}

law mul_succ:
  for a: Nat
  for b: Nat
  {C.mul(a, 1n+b) == C.add(C.mul(a, b), a) : Nat}
