"""Externalized state (the etcd analog): state file, trace log, ownership lease.

Everything the controller needs to resume lives under `<workdir>/.loop/`, so the
process can be killed at any point and restarted (crash-only design).
"""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class State:
    status: str = "pending"  # pending | reconciling | converged | unreachable | thrashing | budget_exhausted | ownership_violation
    phase: str = "idle"  # idle | acting | verifying
    iteration: int = 0  # actor invocations so far
    actor_seconds: float = 0.0
    no_progress_streak: int = 0
    regressions: int = 0
    baseline_passing: list[str] = field(default_factory=list)  # passing set before the candidate commit
    candidate: str | None = None  # sha of the last committed, not-yet-verified action
    target: str | None = None


class Store:
    def __init__(self, workdir: Path):
        self.dir = workdir / ".loop"
        self.dir.mkdir(exist_ok=True)
        ignore = self.dir / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n")  # never let controller state leak into diffs or commits
        self.state_path = self.dir / "state.json"
        self.trace_path = self.dir / "traces.jsonl"

    def exists(self) -> bool:
        return self.state_path.exists()

    def load(self) -> State:
        if not self.state_path.exists():
            return State()
        return State(**json.loads(self.state_path.read_text()))

    def save(self, state: State) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2))
        os.replace(tmp, self.state_path)  # atomic: a crash never leaves half-written state

    def trace(self, event: str, **fields: object) -> None:
        with self.trace_path.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "event": event, **fields}) + "\n")

    def traces(self) -> list[dict]:
        if not self.trace_path.exists():
            return []
        return [json.loads(line) for line in self.trace_path.read_text().splitlines() if line]

    def reset(self) -> None:
        for p in (self.state_path, self.trace_path):
            p.unlink(missing_ok=True)


class LeaseHeld(RuntimeError):
    pass


class Lease:
    """One loop owns one workdir. Prevents conflicting controllers.

    Stale leases (expired, or held by a dead pid on this host) are taken over.
    """

    def __init__(self, store: Store, ttl_s: float):
        self.path = store.dir / "lease.json"
        self.ttl_s = ttl_s
        self.me = {"host": socket.gethostname(), "pid": os.getpid()}

    def _stale(self, held: dict) -> bool:
        if held.get("expires", 0) < time.time():
            return True
        if held.get("host") == self.me["host"]:
            try:
                os.kill(int(held["pid"]), 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
        return False

    def acquire(self) -> None:
        body = json.dumps({**self.me, "expires": time.time() + self.ttl_s})
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    held = json.loads(self.path.read_text())
                except (FileNotFoundError, json.JSONDecodeError):
                    held = {}
                if held and not self._stale(held):
                    raise LeaseHeld(f"workdir owned by {held['host']}:{held['pid']}") from None
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w") as f:
                f.write(body)
            return
        raise LeaseHeld("lost lease race")

    def renew(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**self.me, "expires": time.time() + self.ttl_s}))
        os.replace(tmp, self.path)

    def release(self) -> None:
        try:
            held = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return
        if held.get("pid") == self.me["pid"] and held.get("host") == self.me["host"]:
            self.path.unlink(missing_ok=True)
