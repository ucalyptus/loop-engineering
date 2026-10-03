"""The reconciliation loop: observe -> diff -> act -> gate -> commit -> verify -> repeat.

Failure modes from the K8s playbook and how this controller handles each:

- Thrashing:            every committed action is verified; any check that passed before and
                        fails after triggers a `git revert`. `max_regressions` reverts => halt.
- Stale reads:          state is re-observed at the top of every iteration (optionally from a
                        fresh clone of HEAD), never carried over from memory.
- Infinite reconcile:   `max_iterations`, `max_actor_seconds`, and `stall_iterations` breakers.
- Conflicting loops:    a lease file gives one controller ownership of one workdir; actor
                        changes outside the workdir halt the loop.
- Big-bang actions:     diffs larger than `max_diff_lines` are rejected and discarded.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .manifest import Check, Manifest
from .store import Lease, State, Store

CONVERGED, ERROR, UNREACHABLE, THRASHING, BUDGET, OWNERSHIP = 0, 1, 2, 3, 4, 5
EXIT_CODES = {
    "converged": CONVERGED,
    "unreachable": UNREACHABLE,
    "thrashing": THRASHING,
    "budget_exhausted": BUDGET,
    "ownership_violation": OWNERSHIP,
}
OUTPUT_TAIL = 4000


class LoopError(RuntimeError):
    pass


def _tail(text: str, n: int = OUTPUT_TAIL) -> str:
    return text if len(text) <= n else "…" + text[-n:]


def _sh(cmd: str, cwd: Path, timeout: float, env: dict[str, str] | None = None, stdin: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, shell=True, cwd=cwd, input=stdin, text=True, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
        )
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, out + f"\n[timed out after {timeout:.0f}s]"
    return p.returncode, p.stdout


class Git:
    """All mutations are scoped to the workdir pathspec (`-- .`)."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        code, out = _sh("git rev-parse --show-toplevel", workdir, 30)
        if code != 0:
            raise LoopError(f"workdir must be inside a git repository (externalized state): {workdir}")
        self.top = Path(out.strip()).resolve()
        self.rel = workdir.relative_to(self.top)
        if _sh("git rev-parse --verify -q HEAD", workdir, 30)[0] != 0:
            raise LoopError("repository has no commits; make an initial commit first")

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        p = subprocess.run(["git", *args], cwd=cwd or self.workdir, text=True, capture_output=True)
        if check and p.returncode != 0:
            raise LoopError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
        return p.stdout

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def dirty(self) -> list[str]:
        return self._git("status", "--porcelain", "-uall", "--", ".").splitlines()

    def outside_snapshot(self) -> set[str]:
        if str(self.rel) == ".":
            return set()
        out = self._git("status", "--porcelain", "-uall", "--", ".", f":(exclude){self.rel}", cwd=self.top)
        return set(out.splitlines())

    def stage(self) -> int:
        """Stage all workdir changes; return lines changed (binary files count as 1)."""
        self._git("add", "-A", "--", ".")
        total = 0
        for line in self._git("diff", "--cached", "--numstat", "--", ".").splitlines():
            added, deleted, _ = line.split("\t", 2)
            total += 1 if added == "-" else int(added) + int(deleted)
        return total

    def stat(self) -> str:
        return self._git("diff", "--cached", "--stat", "--", ".")

    def discard(self) -> None:
        self._git("reset", "-q", "--", ".", check=False)
        self._git("checkout", "-q", "HEAD", "--", ".", check=False)
        self._git("clean", "-fdq", "--", ".")
        if self.dirty():
            raise LoopError(f"could not discard workdir changes: {self.dirty()}")

    def commit(self, message: str) -> tuple[bool, str]:
        p = subprocess.run(["git", "commit", "-q", "-m", message, "--", "."], cwd=self.workdir, text=True, capture_output=True)
        return p.returncode == 0, (p.stdout + p.stderr).strip()

    def revert(self, sha: str) -> None:
        self._git("revert", "--no-edit", sha)

    def fresh_clone(self) -> tuple[Path, Path]:
        tmp = Path(tempfile.mkdtemp(prefix="loopctl-"))
        self._git("clone", "-q", "--no-hardlinks", str(self.top), str(tmp / "repo"), cwd=self.top)
        return tmp, tmp / "repo" / self.rel


@dataclass
class Observation:
    passing: list[str]
    failing: list[str]
    output: dict[str, str]  # tail of each failing check's output


def observe(m: Manifest, git: Git) -> Observation:
    """Sense actual state. Fresh-clone mode reads only committed reality, nothing cached locally."""
    tmp = None
    cwd = m.workdir
    if m.fresh_clone:
        tmp, cwd = git.fresh_clone()
    try:
        passing, failing, output = [], [], {}
        for c in m.checks:
            code, out = _sh(c.run, cwd, c.timeout_s)
            if code == 0:
                passing.append(c.name)
            else:
                failing.append(c.name)
                output[c.name] = _tail(out)
        return Observation(passing, failing, output)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def render_prompt(m: Manifest, obs: Observation, target: Check) -> str:
    failing = "\n".join(f"- {name}" for name in obs.failing)
    return f"""You are one iteration of a reconciliation loop. Make ONE small, idempotent change.

Goal (desired state): {m.goal}

Desired state is reached when every check exits 0. Currently failing:
{failing}

Your target this iteration is ONLY check `{target.name}`:
  command: {target.run}
  output (tail):
{obs.output[target.name]}

Rules:
- Read the relevant code before editing. Make the smallest change that makes `{target.name}` pass.
- Do not break checks that currently pass; your change will be reverted if you do.
- Do not modify the checks or files outside {m.workdir}.
- Do not commit; the controller commits after its own gates.
- Changes larger than {m.limits.max_diff_lines} changed lines are rejected.
"""


@dataclass
class Gate:
    ok: bool
    reason: str = ""
    diff_lines: int = 0


def admit(m: Manifest, git: Git, outside_before: set[str], target: str, ask: Callable[[str], bool]) -> Gate:
    """Admission control for a proposed change, cheapest gate first."""
    new_outside = git.outside_snapshot() - outside_before
    if new_outside:
        return Gate(False, "ownership_violation: changed files outside workdir: " + ", ".join(sorted(new_outside)))
    if not git.dirty():
        return Gate(False, "no_op: actor made no changes")
    lines = git.stage()
    if lines > m.limits.max_diff_lines:
        return Gate(False, f"diff_too_large: {lines} > {m.limits.max_diff_lines} lines", lines)
    for hook in m.admission:
        code, out = _sh(hook.run, m.workdir, hook.timeout_s)
        if code != 0:
            return Gate(False, f"admission[{hook.name}]: {_tail(out, 500).strip() or f'exit {code}'}", lines)
    if m.require_approval and not ask(f"Target `{target}`, {lines} changed lines:\n{git.stat()}\nApprove commit? [y/N] "):
        return Gate(False, "approval_denied", lines)
    return Gate(True, "", lines)


def tty_ask(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(prompt).strip().lower() in {"y", "yes"}


class Controller:
    def __init__(
        self,
        m: Manifest,
        *,
        log: Callable[[str], None] = lambda s: print(s, flush=True),
        sleep: Callable[[float], None] = time.sleep,
        ask: Callable[[str], bool] = tty_ask,
    ):
        self.m = m
        self.log = log
        self.sleep = sleep
        self.ask = ask
        self.git = Git(m.workdir)
        self.store = Store(m.workdir)
        ttl = m.actor_timeout_s + sum(c.timeout_s for c in (*m.checks, *m.admission)) + 60
        self.lease = Lease(self.store, ttl)

    def run(self) -> int:
        self.lease.acquire()
        try:
            return self._run()
        finally:
            self.lease.release()

    def _halt(self, st: State, status: str, detail: str = "") -> int:
        st.status, st.phase, st.target = status, "idle", None
        self.store.save(st)
        self.store.trace("halt", status=status, detail=detail, iteration=st.iteration)
        self.log(f"[{self.m.name}] {status}" + (f": {detail}" if detail else ""))
        return EXIT_CODES[status]

    def _recover(self, st: State) -> None:
        dirty = self.git.dirty()
        if not dirty:
            return
        if st.phase != "acting":
            raise LoopError("workdir has uncommitted changes not made by the loop; commit or stash them first:\n" + "\n".join(dirty))
        self.git.discard()  # unverified leftovers from an interrupted action
        st.phase = "idle"
        self.store.save(st)
        self.store.trace("recovered", discarded=dirty)
        self.log(f"[{self.m.name}] discarded unverified changes from interrupted iteration")

    def _verify(self, st: State, obs: Observation) -> bool | None:
        """Check the last committed action. Returns progress, or None if it was reverted."""
        lost = sorted(set(st.baseline_passing) - set(obs.passing))
        candidate, st.candidate, st.phase = st.candidate, None, "idle"
        if lost:
            self.git.revert(candidate)
            st.regressions += 1
            self.store.trace("revert", commit=candidate, broke=lost, regressions=st.regressions)
            self.log(f"[{self.m.name}] reverted {candidate[:8]}: broke {lost}")
            return None
        gained = sorted(set(obs.passing) - set(st.baseline_passing))
        self.store.trace("verified", commit=candidate, gained=gained)
        return bool(gained)

    def _run(self) -> int:
        m, lim, st = self.m, self.m.limits, self.store.load()
        self._recover(st)
        st.status = "reconciling"
        self.store.save(st)

        while True:
            self.lease.renew()
            obs = observe(m, self.git)  # observe before every action; never trust memory
            self.store.trace("observe", head=self.git.head(), passing=obs.passing, failing=obs.failing)
            self.log(f"[{m.name}] observe: {len(obs.passing)}/{len(m.checks)} passing" + (f", failing {obs.failing}" if obs.failing else ""))

            if st.phase == "verifying":
                progress = self._verify(st, obs)
                st.no_progress_streak = 0 if progress else st.no_progress_streak + 1
                self.store.save(st)
                if progress is None:
                    if st.regressions >= lim.max_regressions:
                        return self._halt(st, "thrashing", f"{st.regressions} reverted regressions")
                    continue  # re-observe the reverted state before acting again

            if not obs.failing:
                return self._halt(st, "converged")
            if st.no_progress_streak >= lim.stall_iterations:
                return self._halt(st, "unreachable", f"no progress in {st.no_progress_streak} iterations; still failing {obs.failing}")
            if st.iteration >= lim.max_iterations:
                return self._halt(st, "budget_exhausted", f"max_iterations={lim.max_iterations}")
            if st.actor_seconds >= lim.max_actor_seconds:
                return self._halt(st, "budget_exhausted", f"max_actor_seconds={lim.max_actor_seconds:.0f}")

            if st.no_progress_streak:
                delay = min(lim.backoff_max_s, lim.backoff_base_s * 2 ** (st.no_progress_streak - 1))
                self.log(f"[{m.name}] backoff {delay:.1f}s")
                self.sleep(delay)

            target = next(c for c in m.checks if c.name in obs.failing)  # one target per iteration
            outside_before = self.git.outside_snapshot()
            st.iteration += 1
            st.target, st.phase = target.name, "acting"
            self.store.save(st)  # crash here => next run discards the half-done action
            self.lease.renew()

            self.log(f"[{m.name}] act #{st.iteration}: target `{target.name}`")
            env = {
                **os.environ,
                "LOOP_NAME": m.name,
                "LOOP_GOAL": m.goal,
                "LOOP_WORKDIR": str(m.workdir),
                "LOOP_ITERATION": str(st.iteration),
                "LOOP_TARGET": target.name,
                "LOOP_TARGET_CMD": target.run,
                "LOOP_TARGET_OUTPUT": obs.output[target.name],
                "LOOP_FAILING": json.dumps(obs.failing),
            }
            t0 = time.monotonic()
            code, out = _sh(m.actor, m.workdir, m.actor_timeout_s, env=env, stdin=render_prompt(m, obs, target))
            elapsed = time.monotonic() - t0
            st.actor_seconds += elapsed
            self.store.trace("act", iteration=st.iteration, target=target.name, exit=code, seconds=round(elapsed, 3), output=_tail(out, 1000))

            gate = Gate(False, f"actor_failed: exit {code}") if code != 0 else admit(m, self.git, outside_before, target.name, self.ask)
            if gate.ok:
                ok, msg = self.git.commit(f"loop({m.name}): #{st.iteration} {target.name}")
                if not ok:
                    gate = Gate(False, f"commit_rejected: {_tail(msg, 500)}", gate.diff_lines)

            if not gate.ok:
                self.store.trace("reject", iteration=st.iteration, target=target.name, reason=gate.reason, diff_lines=gate.diff_lines)
                self.log(f"[{m.name}] rejected: {gate.reason}")
                if gate.reason.startswith("ownership_violation"):
                    # Outside changes may be mixed with someone else's work: leave everything for a human.
                    return self._halt(st, "ownership_violation", gate.reason.split(": ", 1)[1])
                self.git.discard()
                st.phase, st.no_progress_streak = "idle", st.no_progress_streak + 1
                self.store.save(st)
                continue

            st.candidate, st.baseline_passing, st.phase = self.git.head(), obs.passing, "verifying"
            self.store.save(st)
            self.store.trace("commit", iteration=st.iteration, target=target.name, commit=st.candidate, diff_lines=gate.diff_lines)
            self.log(f"[{m.name}] committed {st.candidate[:8]} ({gate.diff_lines} lines)")
