#!/usr/bin/env bash
# Exports mlops-north-nov5.html to mlops-north-nov5.pdf: one 16:9 page per slide, for the
# organizers' backup copy. Needs Google Chrome (or set CHROME to a Chromium binary).
set -euo pipefail
cd "$(dirname "$0")"
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[[ -x "$chrome" ]] || { echo "export-pdf: Chrome not found at '$chrome'; set CHROME" >&2; exit 127; }
"$chrome" --headless=new --disable-gpu --no-pdf-header-footer --virtual-time-budget=5000 \
  --print-to-pdf="$PWD/mlops-north-nov5.pdf" "file://$PWD/mlops-north-nov5.html" 2>/dev/null
echo "wrote $PWD/mlops-north-nov5.pdf"
