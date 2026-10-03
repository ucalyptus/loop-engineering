"""loopctl: kubectl for agent loops."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict

from .controller import ERROR, Controller, Git, LoopError, observe
from .manifest import ManifestError, load
from .store import LeaseHeld, Store


def cmd_run(args: argparse.Namespace) -> int:
    return Controller(load(args.manifest)).run()


def cmd_diff(args: argparse.Namespace) -> int:
    """Observe once and show desired vs actual. Exit 0 iff converged."""
    m = load(args.manifest)
    obs = observe(m, Git(m.workdir))
    for c in m.checks:
        print(f"{'✓' if c.name in obs.passing else '✗'} {c.name}")
        if c.name in obs.output and args.verbose:
            print("  " + obs.output[c.name].replace("\n", "\n  "))
    return 0 if not obs.failing else 1


def cmd_status(args: argparse.Namespace) -> int:
    m = load(args.manifest)
    print(json.dumps(asdict(Store(m.workdir).load()), indent=2))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    m = load(args.manifest)
    Store(m.workdir).reset()
    print(f"cleared state and traces for {m.name}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Mine traces for failure patterns: the input to the outer hill-climbing loop."""
    m = load(args.manifest)
    traces = Store(m.workdir).traces()
    if not traces:
        print("no traces")
        return 0
    by = Counter(t["event"] for t in traces)
    fail_counts = Counter(name for t in traces if t["event"] == "observe" for name in t["failing"])
    reject_reasons = Counter(t["reason"].split(":", 1)[0] for t in traces if t["event"] == "reject")
    targets = Counter(t["target"] for t in traces if t["event"] == "act")
    broke = Counter(name for t in traces if t["event"] == "revert" for name in t["broke"])
    actor_s = sum(t["seconds"] for t in traces if t["event"] == "act")
    halts = [t for t in traces if t["event"] == "halt"]

    print(f"{m.name}: {by['act']} actions, {by['commit']} commits, {by['reject']} rejected, {by['revert']} reverted, {actor_s:.1f}s acting")
    if halts:
        last = halts[-1]
        print(f"last outcome: {last['status']}" + (f" ({last['detail']})" if last.get("detail") else ""))
    for title, counter in (
        ("checks observed failing", fail_counts),
        ("actions per target", targets),
        ("rejection reasons", reject_reasons),
        ("checks broken by reverted actions", broke),
    ):
        if counter:
            print(f"\n{title}:")
            for k, v in counter.most_common():
                print(f"  {v:4d}  {k}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="loopctl", description="K8s-style reconciliation loops for coding agents")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (
        ("run", cmd_run, "reconcile until converged or a circuit breaker trips"),
        ("diff", cmd_diff, "observe once: desired vs actual"),
        ("status", cmd_status, "print persisted controller state"),
        ("report", cmd_report, "mine traces for failure patterns"),
        ("reset", cmd_reset, "clear persisted state, budgets and traces"),
    ):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("manifest", help="path to loop.toml")
        sp.set_defaults(fn=fn)
        if name == "diff":
            sp.add_argument("-v", "--verbose", action="store_true", help="show failing check output")
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ManifestError, LoopError, LeaseHeld) as e:
        print(f"loopctl: {e}", file=sys.stderr)
        return ERROR
    except KeyboardInterrupt:
        print("\nloopctl: interrupted; state is persisted, rerun to resume", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
