# Muse worker for loopctl

loopctl's actor is any shell command run in the workdir: prompt on stdin,
`LOOP_*` env vars, edit files, exit 0, do NOT commit. Muse is not a CLI
loopctl can invoke, and there is no Muse hook like `loopctl.ts` for
pi/oh-my-pi — so this worker is a handoff, not a live model call:

1. loopctl invokes `muse-worker.py` as the actor.
2. The worker writes the iteration prompt to a queue file and waits
   (polls every 2s) for a `.done` file.
3. A Muse session reads the prompt, edits the workdir (never commits),
   checks the target itself, then creates the `.done` file.
4. The worker exits 0; loopctl gates the change, commits, verifies, and
   reverts on regression exactly as it would for pi/omp. On timeout the
   worker exits 1 and loopctl treats the iteration as rejected/no-progress,
   committing nothing.

## Use

Manifest snippet:

```toml
actor = "python3 /path/to/muse-worker.py"
actor_timeout_s = 600
```

Run with the queue dir set (default is `queue/` next to the worker):

```bash
PYTHONPATH=<loop-engineering checkout> \
LOOPCTL_MUSE_QUEUE=/path/to/queue \
python3 -m loopctl run loop.muse.toml
```

Env: `LOOPCTL_MUSE_TIMEOUT` (default 540s, keep under `actor_timeout_s`).

## Proven run (buggy calc example)

- Start: 1/4 passing (add, sub, div failing).
- Iter 1 add, iter 2 sub, iter 3 div — each edit made by Muse in the
  workdir, each gated and committed by loopctl.
- End: 4/4 passing, `converged`, exit 0. Report: 3 actions, 3 commits,
  0 rejected, 0 reverted.

## Limits

- This only works while a Muse session is actively watching the queue.
  It is not a background daemon.
- The workdir must be clean before `loopctl run` starts — loopctl refuses
  a dirty workdir (stray `__pycache__` will block it; add it to
  `.gitignore`).
