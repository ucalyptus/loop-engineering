import Base
import ./calc.bend as C

# SPEC (human-owned, frozen by admission): double(n) is n + n, for every n.
# Unlike the add and mul laws, this one needs a proof by induction.

law double_is_add:
  for n: Nat
  {C.double(n) == C.add(n, n) : Nat}
