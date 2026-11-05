#!/usr/bin/env python3
"""Muse worker for loopctl.

loopctl's actor contract: a shell command run in the workdir, prompt on
stdin, LOOP_* env vars, edit files in the workdir, exit 0, do NOT commit.
loopctl then gates, commits, verifies, and reverts on regression.

Muse is not a CLI loopctl can invoke, so this worker does not pretend to
be a model call. It is a handoff:

  1. Write the iteration's prompt + context to a queue file.
  2. Wait (poll) for an external agent (a Muse session) to edit the
     workdir and drop a `.done` file next to the prompt.
  3. Exit 0 when the done file appears, 1 on timeout (loopctl then
     treats the iteration as a rejected/no-progress action, per its
     stall rules, and does NOT commit anything).

Queue dir: $LOOPCTL_MUSE_QUEUE, else <this dir>/queue.
Timeout:   $LOOPCTL_MUSE_TIMEOUT seconds, default 540 (under loopctl's
           default 600s actor_timeout_s in the calc manifest; set both
           together for other manifests).
"""
import os
import sys
import time
from pathlib import Path

QUEUE = Path(os.environ.get("LOOPCTL_MUSE_QUEUE", Path(__file__).parent / "queue"))
TIMEOUT = float(os.environ.get("LOOPCTL_MUSE_TIMEOUT", "540"))
POLL = 2.0


def main() -> int:
    prompt = sys.stdin.read()
    iteration = os.environ.get("LOOP_ITERATION", "?")
    target = os.environ.get("LOOP_TARGET", "?")
    workdir = os.environ.get("LOOP_WORKDIR", os.getcwd())
    QUEUE.mkdir(parents=True, exist_ok=True)
    stem = f"iter-{iteration}-{target}"
    prompt_file = QUEUE / f"{stem}.prompt.md"
    done_file = QUEUE / f"{stem}.done"
    waiting_file = QUEUE / f"{stem}.waiting"
    # A re-run of the same iteration (e.g. after a restart) must not
    # instantly succeed on a stale done file from an earlier run.
    done_file.unlink(missing_ok=True)
    prompt_file.write_text(
        "# loopctl iteration for Muse\n\n"
        f"- iteration: {iteration}\n"
        f"- target check: {target}\n"
        f"- target command: {os.environ.get('LOOP_TARGET_CMD', '')}\n"
        f"- failing checks: {os.environ.get('LOOP_FAILING', '')}\n"
        f"- workdir (edit files HERE, do not commit): {workdir}\n"
        f"- done file (create when edits are ready): {done_file}\n\n"
        "## Prompt from loopctl\n\n"
        f"{prompt}\n"
    )
    waiting_file.touch()
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if done_file.exists():
            waiting_file.unlink(missing_ok=True)
            print(f"[muse-worker] iteration {iteration} target {target}: done file seen, exiting 0")
            return 0
        time.sleep(POLL)
    waiting_file.unlink(missing_ok=True)
    print(f"[muse-worker] iteration {iteration} target {target}: timed out after {TIMEOUT}s", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
