# Persistence — TrueNAS SCALE Docker (opencode / dev container)

The stock-picker code is safe in this repo; the thing that gets lost is the
**container's workspace** (`/workspace` inside the opencode/dev container) on
TrueNAS. Every NAS restart wipes it, which is what happened to the
2026-08-20 session (all its uncommitted fixes were lost and had to be
reworked — see site 0.5.6.11).

## One-time fix (2 minutes, TrueNAS UI)

1. TrueNAS UI -> **Apps** -> your opencode app -> **Edit** (or the
   docker-compose entry).
2. Add a storage mount mapping a persistent dataset onto the workspace:

```yaml
volumes:
  - /mnt/your-pool/opencode-data:/workspace
```

where `/mnt/your-pool/opencode-data` is a dataset you create under
**Datasets** (Apps -> Datasets -> Add Dataset, e.g. `opencode-data`).

3. Save/Redeploy. The container now survives NAS restarts with `/workspace`
   intact.

## Verify

Inside the container after a restart:

```sh
ls /workspace/            # your working copy, still there
```

and on the NAS: `ls /mnt/your-pool/opencode-data` shows the same files.

## What is / and isn't covered

- `/workspace` (the working copy + `portfolio.json`, caches) — covered by the
  volume above.
- The git history lives on GitHub (`RubySapior/stock-picker`) — a `git push`
  is the ultimate backup; commit early, commit often.
- `meta.ai.last_call` counters and `fear_state` live in `portfolio.json`, so
  they persist with the volume too.