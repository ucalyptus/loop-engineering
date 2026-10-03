#!/usr/bin/env bash
# Copies the churn example into a throwaway git repo and reconciles it.
#   ./demo.sh                 offline, deterministic worker (fix_one.py)
#   ./demo.sh loop.pi.toml    pi as the worker (needs pi and a model key)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
manifest="${1:-loop.toml}"
[[ -f "$here/$manifest" ]] || { echo "no such manifest: $manifest" >&2; exit 2; }
work="$(mktemp -d)/churn"
mkdir -p "$work"
(cd "$here" && tar --exclude=__pycache__ --exclude=.loop --exclude=MODEL_CARD.md -cf - .) | (cd "$work" && tar -xf -)
git -C "$work" init -q
git -C "$work" add -A
git -C "$work" -c user.name=demo -c user.email=demo@example.com commit -qm "initial: churn model with planted bugs"

export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" LOOPCTL_ROOT="$root"
export GIT_AUTHOR_NAME=loopctl GIT_AUTHOR_EMAIL=loopctl@example.com
export GIT_COMMITTER_NAME=loopctl GIT_COMMITTER_EMAIL=loopctl@example.com

m="$work/$manifest"
echo "== diff (desired vs actual)"; python3 -m loopctl diff "$m" || true
echo "== run"; status=0; python3 -m loopctl run "$m" || status=$?
echo "== report"; python3 -m loopctl report "$m"
echo "== history"; git -C "$work" log --oneline
echo "workdir: $work"
exit "$status"
