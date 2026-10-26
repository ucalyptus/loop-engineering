#!/usr/bin/env bash
# Copies the Bend example into a throwaway git repo and reconciles it.
#   ./demo.sh                  offline, deterministic worker (fix_one.py)
#   ./demo.sh loop.pi.toml     pi writes the fixes and the proofs
#   ./demo.sh loop.cheat.toml  failure demo: three ways to fake a proof; none gets through
# Needs Bend 2 (https://github.com/bendlang/bend) on PATH or in ~/.bend/bin. --verdict also needs
# the Lean toolchain Bend names (the first check builds its kernel, about 20 s once).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
manifest="${1:-loop.toml}"
[[ -f "$here/$manifest" ]] || { echo "no such manifest: $manifest" >&2; exit 2; }
[[ -x "$HOME/.bend/bin/bend" ]] && export PATH="$HOME/.bend/bin:$PATH"
command -v bend >/dev/null || { echo "bend not found: curl -fsSL https://bend-lang.com/install.sh | sh" >&2; exit 127; }
work="$(mktemp -d)/calc-bend"
mkdir -p "$work"
cp "$here"/*.bend "$here"/{fix_one.py,cheat.py,loop.toml,loop.pi.toml,loop.cheat.toml} "$work"
printf '__pycache__/\n' > "$work/.gitignore"
git -C "$work" init -q
git -C "$work" add -A
git -C "$work" -c user.name=demo -c user.email=demo@example.com commit -qm "initial: calc.bend with planted bugs, open laws"

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
