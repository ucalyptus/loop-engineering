#!/usr/bin/env bash
# Builds slides.pdf (to project) and slides-notes.pdf (slides + speaker notes on a second screen).
# Needs XeLaTeX (TeX Live / MacTeX) and the Helvetica Neue + Menlo fonts that ship with macOS.
set -euo pipefail
cd "$(dirname "$0")"
(cd pic && for f in background title; do xelatex -interaction=nonstopmode -halt-on-error "$f.tex" >/dev/null; done)
latexmk -xelatex -interaction=nonstopmode -halt-on-error -quiet slides.tex
latexmk -xelatex -interaction=nonstopmode -halt-on-error -quiet -jobname=slides-notes \
  -usepretex='\def\withnotes{}' slides.tex
latexmk -c -quiet slides.tex
latexmk -c -quiet -jobname=slides-notes slides.tex
echo "built: $(pwd)/slides.pdf $(pwd)/slides-notes.pdf"
