#!/usr/bin/env bash
# Crash-only demo: start the loop, kill it with Ctrl-C (SIGINT) in the middle of round 2,
# show the half-done edit it left behind, then rerun. The rerun discards the unverified
# change and resumes from the last commit with the same budgets. Offline, about 15 s.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="$(mktemp -d)/calc"
mkdir -p "$work"
cp "$here"/{calc.py,test_calc.py,fix_one.py,loop.slow.toml} "$work"
printf '__pycache__/\n' > "$work/.gitignore"
git -C "$work" init -q
git -C "$work" add -A
git -C "$work" -c user.name=demo -c user.email=demo@example.com commit -qm "initial: buggy calc"

export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" LOOPCTL_ROOT="$root"
export GIT_AUTHOR_NAME=loopctl GIT_AUTHOR_EMAIL=loopctl@example.com
export GIT_COMMITTER_NAME=loopctl GIT_COMMITTER_EMAIL=loopctl@example.com
m="$work/loop.slow.toml"
log="$(mktemp)"  # outside the workdir, or loopctl sees it as a change it did not make

echo "== run 1 (will be killed during round 2)"
set -m  # job control: without it, background jobs start with SIGINT ignored and Ctrl-C does nothing
python3 -m loopctl run "$m" >"$log" 2>&1 &
pid=$!
set +m
tail -f "$log" & tailer=$!
disown "$tailer"
trap 'kill "$tailer" 2>/dev/null || true; rm -f "$log"' EXIT
until grep -q "act #2" "$log"; do
  kill -0 "$pid" 2>/dev/null || { echo "crash-demo: loop exited before round 2" >&2; exit 1; }
  sleep 0.2
done
sleep 1
kill -INT "$pid"
wait "$pid" || true
sleep 0.2; kill "$tailer" 2>/dev/null || true
echo "== left behind: an uncommitted, unverified edit"
git -C "$work" status --short -- .
echo "== loopctl status"
python3 -m loopctl status "$m" | grep -E '"(phase|iteration|target)"'
echo "== run 2 (resume)"
status=0; python3 -m loopctl run "$m" || status=$?
echo "== history"; git -C "$work" log --oneline
exit "$status"
