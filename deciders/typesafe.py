#!/usr/bin/env python3
"""loopctl decider backed by TypeSafe's Jev (https://docs.typesafe.ai).

Contract: loop state as JSON on stdin; prints {"move", "target", "confidence", "reason"} on stdout.
Jev answers typed Choice questions with probabilities in one request: which move
(act / ask_human / stop) and, speculatively, which failing check to target. It never
judges pass/fail; loopctl's checks do that.

Key: TYPESAFE_API_KEY, or TYPESAFE_ENV_FILE pointing at a .env that contains it.
Model: TYPESAFE_MODEL (default jev-latest).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://api.typesafe.ai/v1/systemone"

MOVE_RULES = [
    "You are the decision step of an automated repair loop. A coding agent edits code; "
    "automated checks decide pass/fail. Decide what the loop should do next.",
    "`checks` lists every check, whether it passes, how many times the agent has attempted it, "
    "and the failure output. `recent_events` lists the agent's recent attempts and their outcomes: "
    "`reject` (the change was refused, with a reason), `revert` (the change broke a passing check), "
    "`verified` (the change was kept; `gained` lists checks it fixed). `loop` holds counters and limits.",
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


def api_key() -> str:
    if key := os.environ.get("TYPESAFE_API_KEY"):
        return key
    env_file = os.environ.get("TYPESAFE_ENV_FILE")
    if env_file:
        for line in Path(env_file).expanduser().read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip().removeprefix("export ").strip() == "TYPESAFE_API_KEY" and value.strip():
                return value.strip().strip("'\"")
    sys.exit("typesafe decider: set TYPESAFE_API_KEY or TYPESAFE_ENV_FILE")


def post(body: dict, key: str) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(3):
        req = urllib.request.Request(URL, data=data, method="POST", headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in {429, 503, 529} and attempt < 2:
                time.sleep(0.5 * 2**attempt)
                continue
            sys.exit(f"typesafe decider: HTTP {e.code}: {e.read()[:300].decode(errors='replace')}")
        except urllib.error.URLError as e:
            sys.exit(f"typesafe decider: connection failed: {e.reason}")
    sys.exit("typesafe decider: service unavailable")


def valid_choice(answer: dict, options: list[str]) -> dict:
    try:
        probs = answer["probabilities"]
        nums = [*probs.values(), answer["confidence"]]
        ok = (
            answer["choice"] in options
            and set(probs) == set(options)
            and all(isinstance(n, (int, float)) and math.isfinite(n) and 0 <= n <= 1 for n in nums)
            and abs(sum(probs.values()) - 1) < 0.02
        )
    except (KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        sys.exit(f"typesafe decider: invalid answer {json.dumps(answer)[:300]}")
    return answer


def fmt(probs: dict[str, float]) -> str:
    return " ".join(f"{k}={v:.2f}" for k, v in sorted(probs.items(), key=lambda kv: -kv[1]))


def main() -> None:
    state = json.load(sys.stdin)
    failing = state["failing"]
    by_name = {c["name"]: c for c in state["checks"]}

    questions = {
        "move": {"type": "choice", "instructions": MOVE_RULES, "criteria": MOVES},
    }
    if len(failing) > 1:
        questions["target"] = {
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

    result = post({"model": os.environ.get("TYPESAFE_MODEL", "jev-latest"), "state": state, "questions": questions}, api_key())
    move = valid_choice(result["answers"].get("move", {}), list(MOVES))
    reason = f"move {fmt(move['probabilities'])}"
    target = failing[0]
    if "target" in questions:
        t = valid_choice(result["answers"].get("target", {}), failing)
        target = t["choice"]
        reason += f"; target {fmt(t['probabilities'])}"
    print(json.dumps({"move": move["choice"], "target": target, "confidence": move["confidence"], "reason": reason}))


if __name__ == "__main__":
    main()
