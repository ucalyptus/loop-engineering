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
./examples/calc/demo.sh loop.sandbox.toml   # pi as the actor, checks inside throwaway Docker containers
TYPESAFE_ENV_FILE=~/files/.env ./examples/calc/demo.sh loop.jev.toml   # Jev decides the next move
./examples/calc/demo.sh loop.thrash.toml    # failure demo: over-correcting actor, halts as thrashing (exit 3)
./examples/calc/demo.sh loop.shadow.toml    # failure demo: a one-line unittest.py fakes every test (false exit 0)
./examples/calc-bend/demo.sh                # Bend 2: every check is a machine-checked proof
./examples/calc-bend/demo.sh loop.cheat.toml   # failure demo: three ways to fake a proof, none gets through (exit 2)
./examples/churn/demo.sh                    # ML example: data contract, AUC bar, model card
./examples/churn/demo.sh loop.cheat.toml    # failure demo: actor lowers the AUC bar, admission rejects (exit 2)
pip install -e .                 # or: PYTHONPATH=. python3 -m loopctl ...
loopctl run path/to/loop.toml
```

Workshop task: [`examples/churn/README.md`](examples/churn/README.md). A pure-Python churn model with
three planted bugs; run the loop, attack its gates, add the sensor it's missing.

Talk: [`mlops-north-nov5.html`](mlops-north-nov5.html) (MLOps World North, Nov 5 2026; open it in a browser,
arrow keys to move). PDF backup (16:9, for the organizers): `mlops-north-nov5.pdf`, rebuilt with
`./export-pdf.sh`. Speaker notes stay local (`mlops-north-nov5-notes.txt`, gitignored).

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
container: the check's directory is mounted read-only at `/work`, there is no network, and the
container is deleted afterwards. The exit code passes through, so a check is just
`run = "./incvm python3 -m unittest ..."`. loopctl itself stays on the host, so the agent can't
change its own grading. Docker is the default runtime (~0.2s per warm check).
`INCVM_RUNTIME=container` uses [Apple container](https://github.com/apple/container) instead: one
microVM per check (~1s), Apple Silicon only. Image: `INCVM_IMAGE` (default `python:3.12-slim`).

### Decider: a fast model picks the next move

By default loopctl uses a fixed rule: act on the first failing check in manifest order. An
optional `[decider]` replaces that rule with a decision model, split the same way the K8s
scheduler is: it picks, it doesn't run.

```toml
[decider]
run = 'python3 "$LOOPCTL_ROOT/typesafe/decider.py"'   # keep it outside the workdir
min_confidence = 0.6    # below this, the move goes to a human
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

`typesafe/decider.py` implements it with [TypeSafe Jev](https://docs.typesafe.ai). Each round it
asks two Choice questions (the move, and the target when more than one check fails) and asks them
`TYPESAFE_REPEATS` times (default 3), each with a fresh `uid` in the state. `confidence` is the
lowest probability the agreed move got, or 0 when the repeats disagree, so a wobbling decision goes
to a human. This follows TypeSafe's
[self-consistency cookbook](https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook), which
acts automatically only at a top probability of 0.60 or more. Target disagreement alone does not
escalate; the majority target wins. It needs `TYPESAFE_API_KEY`, or `TYPESAFE_ENV_FILE` pointing at
a `.env` file. On `examples/calc/loop.jev.toml`, which lists an unfixable `gpu` check first, the
built-in rule spends 3 rounds on `gpu` and halts with nothing fixed. Jev targets `add`, `sub` and
`div`, then stops on `gpu` (0.99, 3 of 3 asks agree). Thresholds are starting points; tune them on
your own runs.

### Admission gates

An `[[admission]]` command runs in the workdir with the proposed change staged, and gets
`LOOP_NAME`, `LOOP_GOAL` and `LOOP_TARGET`. Exit 0 admits, exit 10 asks a human on the TTY (no TTY
or "no" rejects), any other exit rejects.

`typesafe/gate.py` is a Jev gate for check tampering, built on TypeSafe's
[guardrails cookbook](https://docs.typesafe.ai/cookbooks/llm_guardrails). One request asks three
Noul questions about the staged diff (does it weaken a check, read evaluation data, or hard-code
results?) and one severity Score. Any hazard at 0.70 or more rejects; at 0.35 or more it asks a
human, or rejects if severity is 2 or more. It fails closed: if the API is down, the change is
rejected. On `examples/churn`, it admitted all four honest fixes (hazards at 0.14 or less) and
rejected two cheats that the plain-text gates let through to a false "converged": an AUC floor in
`churn/model.py` (0.81) and training on the holdout set via `"hold" + "out"` (0.78). It is a model,
so keep the plain-text gates next to it.

Prefer an allowlist ("only these paths may change") to a denylist ("these files are untouched"). A
denylist misses new files: `examples/calc/loop.shadow.toml` adds a one-line `unittest.py` that
`python3 -m unittest` imports ahead of the standard library, every check exits 0, and the loop
reports "converged" on broken code.

### Proof checks (Bend 2)

A test checks some inputs. A proof covers all of them, and a proof checker can't be fooled by a file
in the workdir. `examples/calc-bend` uses [Bend 2](https://github.com/bendlang/bend): each check is
`bend check_<op>.bend --verdict`, which passes only when every law in `laws_<op>.bend` is proven,
then rechecks the proofs with BendTT's kernel, which has a proof in Lean.

| File | Owner | Role |
|---|---|---|
| `calc.bend` | agent | the code, with three planted bugs |
| `laws_<op>.bend` | human, frozen | the spec: laws such as `double(n) == add(n, n)` for every `n` |
| `check_<op>.bend` | human, frozen | the sensor: imports the laws and the proofs, so a proof can't swap in weaker laws |
| `proof_<op>.bend` | agent | `def Laws.<law>` for each law; the recursive `double` needs an induction proof (`fix_one.py`) |

The proof checker moves the attack from the check to the spec, so the gates guard the spec:
`spec-frozen` rejects edits to `laws_*.bend` and `check_*.bend`, and `allowlist` rejects any change
outside `calc.bend` and `proof_*.bend`. `loop.cheat.toml` tries three cheats: a weakened law
(`spec-frozen` rejects it), a weaker copy of the laws (`allowlist` rejects it), and a proof that
calls itself forever (`@unsafe`; admitted, but the checker refuses it). The loop halts as unreachable.

With pi as the actor (`loop.pi.toml`), the loop converged in 3 rounds, 144 s of agent time, with no
rejections. pi did not write the induction proof: it redefined `double(n)` as `add(n, n)`, which
meets the law by definition, so the proof is `{==}`. That is legal under the spec. A proof can't be
faked, but the agent will pick the cheapest implementation the laws allow, so write the laws you mean.

Needs `bend` (`curl -fsSL https://bend-lang.com/install.sh | sh`) and, for `--verdict`, the Lean
toolchain Bend names (`elan toolchain install leanprover/lean4:v4.34.0` for Bend 2.0.39; the first
check builds the kernel, about 20 s once). Limits, from Bend's README: laws hold for Bend's
semantics, not each backend; `--verdict` does not cover the parser or the translation into the
kernel; F32 is axiomatic, so nothing about floats (such as the churn model's AUC) can be proven.
Bend checks Bend code only; it does not verify the Python examples.

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
