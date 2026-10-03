"""Desired state: the declarative manifest (the YAML-manifest analog)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Check:
    """One acceptance criterion. Desired state = every check exits 0."""

    name: str
    run: str
    timeout_s: float = 300.0


@dataclass(frozen=True)
class Limits:
    """Circuit breakers. All counters persist across restarts."""

    max_iterations: int = 20  # actor invocations
    max_actor_seconds: float = 3600.0  # cumulative wall time spent acting (cost budget)
    max_diff_lines: int = 200  # dampening: larger actions are rejected and reverted
    stall_iterations: int = 3  # consecutive no-progress iterations => unreachable
    max_regressions: int = 2  # reverted over-corrections => thrashing
    backoff_base_s: float = 1.0
    backoff_max_s: float = 60.0


@dataclass(frozen=True)
class Decider:
    """Optional fast decision model that picks the next move and target (default: built-in rules).

    It may only choose among failing checks and act / ask_human / stop. It never judges
    pass/fail and cannot override budgets or the thrash/stall breakers.
    """

    run: str  # command: JSON state on stdin, JSON decision on stdout
    min_confidence: float = 0.5  # below this, the move goes to a human
    timeout_s: float = 30.0



@dataclass(frozen=True)
class Manifest:
    path: Path
    name: str
    goal: str
    workdir: Path
    checks: tuple[Check, ...]
    actor: str
    actor_timeout_s: float
    admission: tuple[Check, ...]  # admission webhooks: policy gates on each proposed change
    require_approval: bool  # human-in-the-loop gate before commit
    fresh_clone: bool  # observe a fresh clone of HEAD instead of the working tree
    limits: Limits
    decider: Decider | None  # None => built-in rules


def _checks(raw: object, key: str) -> tuple[Check, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ManifestError(f"[[{key}]] must be an array of tables")
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "name" not in item or "run" not in item:
            raise ManifestError(f"{key}[{i}] needs `name` and `run`")
        out.append(Check(str(item["name"]), str(item["run"]), float(item.get("timeout_s", 300.0))))
    names = [c.name for c in out]
    if len(set(names)) != len(names):
        raise ManifestError(f"duplicate {key} names: {names}")
    return tuple(out)


def load(path: str | Path) -> Manifest:
    path = Path(path).resolve()
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ManifestError(f"manifest not found: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{path}: {e}") from None

    for key in ("name", "goal", "actor"):
        if not data.get(key):
            raise ManifestError(f"missing required key `{key}`")

    checks = _checks(data.get("checks"), "checks")
    if not checks:
        raise ManifestError("at least one [[checks]] entry is required")

    known = {f for f in Limits.__dataclass_fields__}
    raw_limits = data.get("limits", {})
    unknown = set(raw_limits) - known
    if unknown:
        raise ManifestError(f"unknown [limits] keys: {sorted(unknown)}")

    workdir = (path.parent / data.get("workdir", ".")).resolve()
    if not workdir.is_dir():
        raise ManifestError(f"workdir does not exist: {workdir}")

    return Manifest(
        path=path,
        name=str(data["name"]),
        goal=str(data["goal"]),
        workdir=workdir,
        checks=checks,
        actor=str(data["actor"]),
        actor_timeout_s=float(data.get("actor_timeout_s", 900.0)),
        admission=_checks(data.get("admission"), "admission"),
        require_approval=bool(data.get("require_approval", False)),
        fresh_clone=bool(data.get("fresh_clone", False)),
        limits=Limits(**raw_limits),
        decider=_decider(data.get("decider")),
    )


def _decider(raw: object) -> Decider | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw.get("run"):
        raise ManifestError("[decider] needs `run`")
    unknown = set(raw) - set(Decider.__dataclass_fields__)
    if unknown:
        raise ManifestError(f"unknown [decider] keys: {sorted(unknown)}")
    d = Decider(str(raw["run"]), float(raw.get("min_confidence", 0.5)), float(raw.get("timeout_s", 30.0)))
    if not 0 <= d.min_confidence <= 1:
        raise ManifestError("[decider] min_confidence must be between 0 and 1")
    return d
