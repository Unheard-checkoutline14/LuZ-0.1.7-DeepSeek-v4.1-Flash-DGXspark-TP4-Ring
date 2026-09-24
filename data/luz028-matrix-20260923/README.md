# `luz028-matrix-20260923/` — LuZ-0.2.8 full matrix (PR 4K–512K × C1–16)

`RUN_TAG = LUZ028_MATRIX4K512K_20260923T150740Z` · 2026-09-23 15:07:40Z → 16:56:29Z
(1 h 48 min 49 s) · **50/50 cells, zero VOID / zero ABORT**.

Measured build: **`dsv41-sglang-optimized:0.2.8`**, content identity **`4cca364c46778423`**
(see `IDENTITY.txt`; the same value all four production nodes report). KV anchors frozen at
`SEQ=16` / `context_length=600000` / `max_total_num_tokens=9600000` — verified against the
runtime banner **and** the container env (`diff = 0`).

## What is here

| file | what it holds |
|---|---|
| `IDENTITY.txt` | run identity: TAG, mode, sizes/concurrency ladders, chunk, image + `content_id`, `env_md5` — as stamped by the frozen orchestrator |
| `STATUS.tsv` | the collector's 50-row completion table (40 PR + 10 DE-legacy), deploy-root masked (see below) |
| `summary.json` | 40 PR cells, recomputed from `raw/` locally (fields: `prompt_tokens`, `wall_s`, `total_tps`, `ttft_first_s`, `ttft_last_s`) |
| `TABLE.md` | the same 40 cells rendered as the 8×5 board + the 1-D view |
| `raw/<size>-c<conc>-w0.json` | 40 per-stream raw records (verbatim copies of each cell's `-w0.json`) |
| `de-w41-triage-superseded/` | 10 DE logs from the window's legacy `w41_de_triage.py` arm — **superseded, not the published DE caliber** (see below) |

## Caliber

The only authoritative PR aggregation is `render()`'s:

```
total t/s = Σ(prompt tokens of ok streams) / (max t_end − min t0)
```

Every value in `summary.json` / `TABLE.md` was recomputed from the per-stream `raw/` files
and **asserted equal to the server-side per-cell `TABLE.md`** (tolerance 0.01 t/s) before this
archive was written. One run per cell ⇒ no error bars; treat only large cross-family gaps as
results.

**Peak: 5,823.11 t/s @ 65536 × C2.** The single hard gate (`524288-C1 > 4500`) measured
**5042.18 t/s (+12.05%) ⇒ PASS**.

> ⚠ **`4096` is `NON_ALIGNED`** (half a chunk): it is listed for completeness and must not be
> cross-compared with whole-chunk rows.

> ⚠ **The harness stamps a constant build label `(v18/0.2.4)` into per-cell `TABLE.md`
> headers.** That label is a hardcoded string, not a measurement — the measured build here
> is 0.2.8 (`IDENTITY.txt`). Do not read the version off a `TABLE.md` header.

## Reproduction

`raw/*.json` are self-describing; the full table can be rebuilt with a few lines:

```python
import json, glob
for p in sorted(glob.glob('raw/*.json')):
    recs = json.load(open(p))
    tok  = sum(r['prompt_tokens'] for r in recs)
    wall = max(r['t_end'] for r in recs) - min(r['t0'] for r in recs)
    print(p, round(tok / wall, 2))
```

## `de-w41-triage-superseded/` — why the legacy DE logs are here but are not the caliber

These 10 logs come from the window's DE leg, measured with `w41_de_triage.py` under a
**grammar-constrained** caliber (`--json-schema` folds `coding`/`json` into one arm and pulls
the run off the prompt-label axis). Four of the ten runs were truncated by a documented
grammar early-EOS path, which made the collector's own `min`-based verdict read as FAIL.

The public DE caliber is **SD-1** (prompt-label types, no guided decoding). It was re-run
separately — see [`../luz028-de-sd1-20260924/`](../luz028-de-sd1-20260924/) — and those
20 cells are the ones to quote. The logs are kept here only so the window's full 50-cell
record stays auditable; their numbers must **not** be mixed into any DE table.

## Masking note

`STATUS.tsv` had the deployment root path (`/home/<user>/dsv41-flash-dgxsparks`) replaced with
`<deploy-root>`; nothing else was altered. All other files are verbatim copies of the runs'
own output. The archive passes `scripts/check_redaction.py` (fail-closed leak scan).