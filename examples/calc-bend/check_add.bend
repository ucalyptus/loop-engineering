import Base
import ./laws_add.bend as Laws
import ./proof_add.bend as Proof

# CHECK ENTRY (human-owned, frozen by admission). The sensor for `add`:
# `bend check_add.bend --verdict` passes only if every law in laws_add.bend is
# proven. It names the laws file itself, so a proof cannot swap in a weaker copy.
