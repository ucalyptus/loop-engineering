import Base
import ./laws_double.bend as Laws
import ./proof_double.bend as Proof

# CHECK ENTRY (human-owned, frozen by admission). The sensor for `double`:
# `bend check_double.bend --verdict` passes only if every law in laws_double.bend is
# proven. It names the laws file itself, so a proof cannot swap in a weaker copy.
