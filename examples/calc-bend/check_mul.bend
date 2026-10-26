import Base
import ./laws_mul.bend as Laws
import ./proof_mul.bend as Proof

# CHECK ENTRY (human-owned, frozen by admission). The sensor for `mul`:
# `bend check_mul.bend --verdict` passes only if every law in laws_mul.bend is
# proven. It names the laws file itself, so a proof cannot swap in a weaker copy.
