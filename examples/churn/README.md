# Churn model: a loop for an ML pipeline

A tiny customer-churn model with three planted bugs. The loop's job is to make it ship-ready.
Everything is plain Python: no numpy, no scikit-learn, nothing to `pip install`.

**Desired state** (`loop.toml`):

| Check | Command | Means |
|---|---|---|
| `schema` | `python3 validate.py` | raw data matches `schema.json`; the feature pipeline emits finite floats |
| `quality` | `python3 eval.py --min-auc 0.85` | train on `data/train.csv`, holdout AUC ≥ 0.85 |
| `model-card` | `python3 check_card.py` | `MODEL_CARD.md` has the required sections and documents every feature |

**Admission gates** (the agent can't move the goalposts):
- `sensors-untouched`: no edits to `eval.py`, `validate.py`, `check_card.py`, `schema.json` or `data/`.
- `no-holdout-in-model-code`: model code must not mention the holdout set (a crude leakage guard).

## Setup

You need Python 3.11+ and git. From the repo root:

```bash
python3 --version          # 3.11 or newer
./examples/churn/demo.sh   # offline: a scripted worker, ~5 seconds
```

The demo copies this folder into a temporary git repo, so your checkout is never modified.

## The task

1. **Watch it converge.** Run `./examples/churn/demo.sh`. It takes 4 commits. Why did `quality`
   need two rounds, and why wasn't the first one reverted?
2. **Use a real agent.** Run `./examples/churn/demo.sh loop.pi.toml`, or edit `actor` in that file
   for your agent: `'claude -p --permission-mode acceptEdits "$(cat)"'`, Codex, and so on. Compare its fixes
   with `fix_one.py`.
3. **Be the adversary.** Write a worker that cheats: lower the bar in `eval.py`, or read the holdout
   file from `churn/model.py`. Watch the admission gates reject it. Then find a cheat the gates
   *don't* catch. (Hint: the leakage guard only looks for one word.)
4. **Add a sensor.** Ashby's law: the loop can only fix what it can see. Add a check this loop is
   missing: recall on churners, calibration, or AUC per contract type. Does it still converge?
5. **Stretch: add a decider.** Copy the `[decider]` block from `../calc/loop.jev.toml` and let
   TypeSafe Jev pick the next move.

Stuck on setup or the task? Ask Sayantan after the talk.

<details>
<summary>Spoilers: the three planted bugs</summary>

1. `churn/features.py` passes `contract` through as a raw string instead of one-hot encoding it,
   so the pipeline emits non-numeric features (`schema` fails, and `eval.py` crashes).
2. `churn/model.py` scales features when training but not when predicting (train/serve skew).
   Holdout AUC: 0.74.
3. `churn/features.py` drops `support_calls`, one of the strongest signals. Holdout AUC: 0.82.

With all three fixed, holdout AUC is 0.874. Each bug alone keeps it below 0.85.
</details>

## Files

| File | Role |
|---|---|
| `churn/features.py`, `churn/model.py`, `churn/data.py` | the code under repair |
| `validate.py`, `eval.py`, `check_card.py`, `schema.json`, `data/` | sensors and data; off limits to the agent |
| `fix_one.py` | scripted offline worker: one anchored fix per round |
| `loop.toml`, `loop.pi.toml` | manifests: scripted worker and pi |
| `make_data.py` | regenerates the synthetic data (seeded; the CSVs are committed) |
