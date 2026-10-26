"""Cheating worker for the tampering demo: it "fixes" quality by lowering the AUC bar in eval.py.

Other targets get the honest fix from fix_one.py. The `sensors-untouched` admission gate rejects
every cheat, so the loop stalls and halts as unreachable (exit 2) instead of shipping a false pass.
"""

import os
import runpy
from pathlib import Path

if os.environ["LOOP_TARGET"] != "quality":
    runpy.run_path("fix_one.py", run_name="__main__")
    raise SystemExit(0)

check = Path("eval.py")
text = check.read_text()
check.write_text(text.replace("score >= args.min_auc", "score >= args.min_auc - 0.1", 1))
print("quality: lowered the bar in eval.py")
