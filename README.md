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
./examples/calc/demo.sh                     # offline demo with a deterministic actor
./examples/calc/demo.sh loop.pi.toml        # pi as the actor
./examples/calc/demo.sh loop.sandbox.toml   # pi as the actor, checks inside Apple container VMs
TYPESAFE_ENV_FILE=~/files/.env ./examples/calc/demo.sh loop.jev.toml   # Jev decides the next move
./examples/churn/demo.sh                    # ML example: data contract, AUC bar, model card
pip install -e .                 # or: PYTHONPATH=. python3 -m loopctl ...
loopctl run path/to/loop.toml
```

Workshop task: [`examples/churn/README.md`](examples/churn/README.md). A pure-Python churn model with
three planted bugs; run the loop, attack its gates, add the sensor it's missing.

Talk: `talk/slides.pdf` (MLOps North, Nov 5 2026); speaker notes in `talk/slides-notes.pdf`. Rebuild with `talk/build.sh`.

| Command | K8s analog | Does |
|---|---|---|
| `loopctl run M` | controller | reconcile until converged / halted |
| `loopctl diff M [-v]` | `kubectl diff` | observe once, show desired vs actual |
| `loopctl status M` | `kubectl get -o yaml` | persisted controller state |
| `loopctl report M` | metrics | mine traces for failure patterns |
| `loopctl reset M` | — | clear state, budgets, traces |

Exit codes: `0` converged, `1` error, `2` unreachable, `3` thrashing, `4` budget exhausted,
`5` ownership violation, `6` needs a human (decider escalated, no one approved).

## Manifest

```toml
name = "calc"
goal = "calc.py arithmetic behaves as test_calc.py specifies."
workdir = "."                      # must be inside a git repo with ≥1 commit
actor = 'pi -p "$(cat)"'          # prompt arrives on stdin; "$(cat)" passes it as an argument
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

### Using an agent harness

loopctl calls the agent; the agent doesn't need a plugin. Any CLI with a one-shot mode works:

```toml
actor = 'pi -p "$(cat)"'                              # pi
actor = 'claude -p --permission-mode acceptEdits "$(cat)"'   # Claude Code
```

### Sandboxing checks (brain outside, hands inside)

Checks run code the agent just wrote. `examples/calc/incvm` runs one check in a throwaway
[Apple container](https://github.com/apple/container) VM: the check's directory is mounted
read-only at `/work`, there is no network, and the VM is deleted afterwards. The exit code passes
through, so a check is just `run = "./incvm python3 -m unittest ..."`. loopctl itself stays on the
host, so the agent can't change its own grading. Needs Apple Silicon; each check pays one VM
boot (~1s). Image: `INCVM_IMAGE` (default `python:3.12-slim`).

### Decider: a fast model picks the next move

By default loopctl uses a fixed rule: act on the first failing check in manifest order. An
optional `[decider]` replaces that rule with a decision model, split the same way the K8s
scheduler is: it picks, it doesn't run.

```toml
[decider]
run = 'python3 "$LOOPCTL_ROOT/deciders/typesafe.py"'   # keep it outside the workdir
min_confidence = 0.5    # below this, the move goes to a human
timeout_s = 30
```

Contract: the command gets JSON on stdin (goal, every check with pass/fail, attempts and failure
output, loop counters, the last 12 act/reject/revert/verified events). It prints
`{"move": "act"|"ask_human"|"stop", "target": <failing check>, "confidence": 0..1, "reason": "..."}`.

What it can't do, by design:
- Judge pass/fail or declare success. Only the checks converge the loop.
- Pick a check that isn't failing, or skip the budget, stall and thrash breakers.
- Act on a shaky call. `ask_human`, or any move under `min_confidence` (including an unsure
  `stop`), asks on the TTY. With no TTY, or a "no", the loop halts with `needs_human` (exit 6).
- Break the loop. A crash, timeout or invalid answer is logged as `decider_error` and that round
  falls back to the built-in rule.

`deciders/typesafe.py` implements it with [TypeSafe Jev](https://docs.typesafe.ai). It sends one
request per round with two Choice questions: the move, and, when more than one check fails, the
target. It needs `TYPESAFE_API_KEY`, or `TYPESAFE_ENV_FILE` pointing at a `.env` file. On
`examples/calc/loop.jev.toml`, which lists an unfixable `gpu` check first, the built-in rule
spends 3 rounds on `gpu` and halts with nothing fixed. Jev targets `add`, `sub` and `div`, then
stops on `gpu` (0.97). Confidence thresholds are starting points; tune them on your own runs.

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
| Scheduler (filter, score, pick) | `[decider]`: a fast model picks the move and target; checks still judge |
| Hill-climbing machine (traces) | `.loop/traces.jsonl` + `loopctl report` |

## Behavior notes

- The workdir must be clean at start. The loop's own state lives in `.loop/` (self-gitignored).
- All git mutations are scoped to the workdir pathspec. `discard` runs `git checkout HEAD -- .`
  and `git clean -fd -- .` inside the workdir, and only for changes the actor made.
- Outside-workdir detection compares `git status` before/after the actor. A file that was
  already dirty before the actor ran and is edited again is not detected.
- Halted runs keep their counters; rerunning resumes against the same budgets. Use `reset` to start over.
