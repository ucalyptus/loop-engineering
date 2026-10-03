# loopctl

K8s-style reconciliation loops for coding agents. Companion code for
[Loop Engineering Is Just K8s-Style Orchestration](https://blog.ucalyptus.me/p/loop-engineering-is-just-k8s-style).

Declare the desired state (checks that must exit 0). The controller observes, diffs, lets an
agent make **one** small change toward **one** failing check, gates it, commits it, verifies it,
and repeats until converged or a circuit breaker trips. Python ≥3.11, stdlib only.

```
observe ──► diff ──► act (1 target) ──► admit ──► commit ──► verify ─┐
   ▲                                                                  │
   └──────────── revert on regression / backoff on no progress ◄──────┘
```

## Quick start

```bash
./examples/calc/demo.sh          # offline demo with a deterministic actor
pip install -e .                 # or: PYTHONPATH=. python3 -m loopctl ...
loopctl run path/to/loop.toml
```

| Command | K8s analog | Does |
|---|---|---|
| `loopctl run M` | controller | reconcile until converged / halted |
| `loopctl diff M [-v]` | `kubectl diff` | observe once, show desired vs actual |
| `loopctl status M` | `kubectl get -o yaml` | persisted controller state |
| `loopctl report M` | metrics | mine traces for failure patterns |
| `loopctl reset M` | — | clear state, budgets, traces |

Exit codes: `0` converged, `1` error, `2` unreachable, `3` thrashing, `4` budget exhausted,
`5` ownership violation.

## Manifest

```toml
name = "calc"
goal = "calc.py arithmetic behaves as test_calc.py specifies."
workdir = "."                      # must be inside a git repo with ≥1 commit
actor = "claude -p --permission-mode acceptEdits"
actor_timeout_s = 600
fresh_clone = true                 # observe a fresh clone of HEAD (no stale local state)
require_approval = false           # y/N prompt before each commit; denied without a TTY

[[checks]]                         # desired state; order = target priority
name = "add"
run = "python3 -m unittest -q test_calc.TestCalc.test_add"
timeout_s = 300

[[admission]]                      # policy gates on each staged change; nonzero = reject
name = "tests-unchanged"
run = "git diff --cached --quiet -- test_calc.py"

[limits]
max_iterations = 20                # actor invocations
max_actor_seconds = 3600           # cumulative actor wall time
max_diff_lines = 200               # larger changes are rejected and discarded
stall_iterations = 3               # consecutive no-progress iterations => unreachable
max_regressions = 2                # reverted over-corrections => thrashing
backoff_base_s = 1.0               # exponential backoff while not progressing
backoff_max_s = 60.0
```

### Actor contract

The actor is any shell command run in `workdir`. It gets a prompt on stdin and these env vars:
`LOOP_NAME`, `LOOP_GOAL`, `LOOP_WORKDIR`, `LOOP_ITERATION`, `LOOP_TARGET`, `LOOP_TARGET_CMD`,
`LOOP_TARGET_OUTPUT`, `LOOP_FAILING` (JSON list). It edits files and exits 0. It must not commit.
Non-zero exit = rejected action.

## Post → code

| Post concept | Implementation |
|---|---|
| Desired state / YAML manifest | `[[checks]]` in `loop.toml` (`manifest.py`) |
| Observe → diff → act → repeat | `Controller._run` (`controller.py`) |
| etcd / externalized state | git commits + `.loop/state.json` (atomic writes) |
| Crash-only design | kill anytime; rerun discards unverified changes and resumes with budgets intact |
| Fresh-clone loop / stale reads | `fresh_clone = true` runs checks in a fresh clone of HEAD each iteration |
| Admission webhooks | `[[admission]]` commands + git hooks on commit |
| Human-in-the-loop gate | `require_approval` |
| RBAC / scoped ownership | lease file (one controller per workdir); actor edits outside workdir halt the loop |
| Small diffs, dampening | one target per iteration, `max_diff_lines`, exponential backoff |
| Thrashing | each commit is verified; breaking a passing check ⇒ `git revert`; `max_regressions` |
| Infinite reconciliation | `max_iterations`, `max_actor_seconds`, `stall_iterations` |
| Hill-climbing machine (traces) | `.loop/traces.jsonl` + `loopctl report` |

## Behavior notes

- The workdir must be clean at start. The loop's own state lives in `.loop/` (self-gitignored).
- All git mutations are scoped to the workdir pathspec. `discard` runs `git checkout HEAD -- .`
  and `git clean -fd -- .` inside the workdir, and only for changes the actor made.
- Outside-workdir detection compares `git status` before/after the actor. A file that was
  already dirty before the actor ran and is edited again is not detected.
- Halted runs keep their counters; rerunning resumes against the same budgets. Use `reset` to start over.
