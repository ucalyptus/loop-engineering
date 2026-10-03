#!/usr/bin/env bash
# Copies the example into a throwaway git repo and reconciles it.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="$(mktemp -d)/calc"
mkdir -p "$work"
cp "$here"/{calc.py,test_calc.py,fix_one.py,loop.toml} "$work"
git -C "$work" init -q
git -C "$work" add -A
git -C "$work" -c user.name=demo -c user.email=demo@example.com commit -qm "initial: buggy calc"

export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
export GIT_AUTHOR_NAME=loopctl GIT_AUTHOR_EMAIL=loopctl@example.com
export GIT_COMMITTER_NAME=loopctl GIT_COMMITTER_EMAIL=loopctl@example.com

echo "== diff (desired vs actual)"; python3 -m loopctl diff "$work/loop.toml" || true
echo "== run";  python3 -m loopctl run "$work/loop.toml"
echo "== report"; python3 -m loopctl report "$work/loop.toml"
echo "== history"; git -C "$work" log --oneline
echo "workdir: $work"
