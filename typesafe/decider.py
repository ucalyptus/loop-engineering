#!/usr/bin/env python3
"""loopctl decider backed by TypeSafe Jev.

Contract: loop state as JSON on stdin; prints {"move", "target", "confidence", "reason"} on stdout.
Jev answers typed Choice questions: which move (act / ask_human / stop) and, when more than one
check fails, which failing check to target. It never judges pass/fail; loopctl's checks do that.

Self-consistency (https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook): the same
question goes out TYPESAFE_REPEATS times (default 3), each with a fresh `uid` in the state.
`confidence` is the lowest probability the agreed move got across repeats, and 0 if the repeats
disagree, so loopctl sends a wobbling decision to a human. The cookbook acts automatically only
at a top probability of 0.60 or more; set `min_confidence = 0.6` in the manifest to match.
Disagreement on the target alone does not escalate: picking among failing checks is low risk,
so the majority target wins.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import ts_api

REPEATS = max(1, int(os.environ.get("TYPESAFE_REPEATS", "3")))

MOVE_RULES = [
    "You are the decision step of an automated repair loop. A coding agent edits code; "
    "automated checks decide pass/fail. Decide what the loop should do next.",
    "`checks` lists every check, whether it passes, how many times the agent has attempted it, "
    "and the failure output. `recent_events` lists the agent's recent attempts and their outcomes: "
    "`reject` (the change was refused, with a reason), `revert` (the change broke a passing check), "
    "`verified` (the change was kept; `gained` lists checks it fixed). `loop` holds counters and limits. "
    "`uid` is a random request id; ignore it.",
]
MOVES = {
    "act": "Let the coding agent attempt a fix. Right when at least one failing check has output that "
    "points to something fixable by editing code in this repository, and recent attempts are not "
    "repeatedly failing in the same way.",
    "ask_human": "Escalate to a person. Right when recent attempts keep failing the same way "
    "(repeated rejections or reverts on the same check), when checks contradict each other, or when "
    "fixing the remaining checks would require changing the checks themselves.",
    "stop": "Give up. Right only when every remaining failure clearly cannot be fixed by editing code "
    "in this repository, for example missing hardware, missing system tools, no network, or missing credentials.",
}
TARGET_RULES = (
    "Which failing check should the coding agent work on next? Prefer a check whose failure output "
    "points to a clear, local code fix, and a check that other failures probably depend on. Avoid a "
    "check whose recent attempts kept failing, unless every other failing check is worse."
)


def questions(state: dict) -> dict:
    q = {"move": {"type": "choice", "instructions": MOVE_RULES, "criteria": MOVES}}
    failing = state["failing"]
    if len(failing) > 1:
        by_name = {c["name"]: c for c in state["checks"]}
        q["target"] = {
            "type": "choice",
            "instructions": [*MOVE_RULES, TARGET_RULES],
            "criteria": {
                name: {
                    "check": name,
                    "command": by_name[name]["command"],
                    "attempts_so_far": by_name[name]["attempts"],
                    "failure_output": by_name[name].get("failure_output", "")[-600:],
                }
                for name in failing
            },
        }
    return q


def aggregate(moves: list[dict], targets: list[str], failing: list[str]) -> dict:
    """Combine repeated answers. Pure function: testable without the API."""
    picked = Counter(m["choice"] for m in moves)
    move, votes = picked.most_common(1)[0]
    agree = votes == len(moves)
    confidence = min(m["probabilities"][move] for m in moves) if agree else 0.0
    target = Counter(targets).most_common(1)[0][0] if targets else failing[0]
    tally = ", ".join(f"{k}×{v}" for k, v in picked.most_common())
    reason = f"move {tally} over {len(moves)} asks; p({move}) min {min(m['probabilities'][move] for m in moves):.2f}"
    if targets:
        reason += f"; target {', '.join(f'{k}×{v}' for k, v in Counter(targets).most_common())}"
    if not agree:
        reason += "; repeats disagree"
    return {"move": move, "target": target, "confidence": round(confidence, 4), "reason": reason}


def main() -> None:
    state = json.load(sys.stdin)
    q = questions(state)
    key = ts_api.api_key()
    with ThreadPoolExecutor(REPEATS) as pool:
        runs = list(pool.map(lambda _: ts_api.ask({**state, "uid": secrets.token_hex(4)}, q, key), range(REPEATS)))
    moves = [ts_api.choice(a, "move", list(MOVES)) for a in runs]
    targets = [ts_api.choice(a, "target", state["failing"])["choice"] for a in runs] if "target" in q else []
    print(json.dumps(aggregate(moves, targets, state["failing"])))


if __name__ == "__main__":
    try:
        main()
    except ts_api.TypeSafeError as e:
        ts_api.fail("typesafe decider", e)
