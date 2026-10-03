"""Shared TypeSafe client for loopctl's decider and admission gate. Standard library only.

API reference: https://docs.typesafe.ai/api
Key: TYPESAFE_API_KEY, or TYPESAFE_ENV_FILE pointing at a .env file that contains it.
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
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")


class TypeSafeError(RuntimeError):
    pass


def api_key() -> str:
    if key := os.environ.get("TYPESAFE_API_KEY"):
        return key
    env_file = os.environ.get("TYPESAFE_ENV_FILE")
    if env_file:
        for line in Path(env_file).expanduser().read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip().removeprefix("export ").strip() == "TYPESAFE_API_KEY" and value.strip():
                return value.strip().strip("'\"")
    raise TypeSafeError("set TYPESAFE_API_KEY or TYPESAFE_ENV_FILE")


def ask(state: object, questions: dict, key: str) -> dict:
    """One /v1/systemone request; returns the `answers` map. Retries 429/503/529 with backoff."""
    data = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    for attempt in range(3):
        req = urllib.request.Request(URL, data=data, method="POST", headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)["answers"]
        except urllib.error.HTTPError as e:
            if e.code in {429, 503, 529} and attempt < 2:
                time.sleep(0.5 * 2**attempt)
                continue
            raise TypeSafeError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from None
        except urllib.error.URLError as e:
            raise TypeSafeError(f"connection failed: {e.reason}") from None
    raise TypeSafeError("service unavailable")


def _prob(n: object) -> bool:
    return isinstance(n, (int, float)) and math.isfinite(n) and 0 <= n <= 1


def choice(answers: dict, qid: str, options: list[str]) -> dict:
    """A validated Choice answer: `choice` is one of `options`, probabilities sum to 1."""
    a = answers.get(qid, {})
    try:
        probs = a["probabilities"]
        ok = (
            a["choice"] in options
            and set(probs) == set(options)
            and all(_prob(v) for v in [*probs.values(), a["confidence"]])
            and abs(sum(probs.values()) - 1) < 0.02
        )
    except (KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        raise TypeSafeError(f"invalid {qid} answer: {json.dumps(a)[:300]}")
    return a


def noul(answers: dict, qid: str) -> float:
    """A validated Noul answer: probability that the condition holds."""
    v = answers.get(qid, {}).get("noul")
    if not _prob(v):
        raise TypeSafeError(f"invalid {qid} answer: {json.dumps(answers.get(qid))[:300]}")
    return float(v)


def score(answers: dict, qid: str, levels: int) -> float:
    """A validated Score answer: probability-weighted level, 0 .. levels-1."""
    v = answers.get(qid, {}).get("score")
    if not isinstance(v, (int, float)) or not 0 <= v <= levels - 1:
        raise TypeSafeError(f"invalid {qid} answer: {json.dumps(answers.get(qid))[:300]}")
    return float(v)


def fail(who: str, err: Exception, code: int = 1) -> None:
    print(f"{who}: {err}", file=sys.stderr)
    sys.exit(code)
