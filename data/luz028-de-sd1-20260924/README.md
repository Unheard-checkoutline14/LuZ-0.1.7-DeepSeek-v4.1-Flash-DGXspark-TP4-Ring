# `luz028-de-sd1-20260924/` — DE SD-1 retest on LuZ-0.2.8 (the published DE caliber)

`RUN_TAG = LUZ028_DE_SD1_20260924` · started 2026-09-24T00:49:32Z → COMPLETE 01:43:54Z ·
**20/20 cells valid**: 4 prompt-label types × 5 concurrencies × 3 waves, `max_tokens=2048`,
`grammar = None` on every cell (no guided decoding).

This is the **authoritative DE archive for 0.2.8**. It supersedes the window's legacy
`w41_de_triage.py` arm (kept, demoted, under
[`../luz028-matrix-20260923/de-w41-triage-superseded/`](../luz028-matrix-20260923/)).

## What is here

| file | what it holds |
|---|---|
| `de_v3_matrix.json` | the full 20-cell matrix + `_meta` (SD-1 protocol text, run tag, model, waves, ladders) |
| `de_<type>_c<conc>.json` × 20 | per-cell raw records (per-stream timestamps, tokens, ttft) |
| `compare_vs_024.py` | the fail-closed comparison script that produced every number in the verdict report (exits 1 on any missing cell / `grammar != None` / `ct != 2048` / failed stream) |
| `preflight.txt` | pre-run identity + anchor record, deploy-root masked (see below) |
| `run.log` | the run's own log, deploy-root masked (see below) |
| `COMPLETE` | completion stamp (`LUZ028_DE_SD1_20260924`, 2026-09-24T01:43:54) |
| `MANIFEST.md5` | the **server-side** md5 manifest of all 24 files as produced on the deployment host |

## The result, in one table

Cell value = `statistics.median` of `decode = (ct−1)/(t_last−t_first)` over every ok stream of
every wave. Baseline = the 0.2.4-era SD-1 matrix at
[`../dev3-v18-20260920/`](../dev3-v18-20260920/) (same protocol, same ladders). Drift bands
(user-ruled): ≤5% PASS · 5–10% WATCH · >10% INVESTIGATE.

| type | C1 | C2 | C4 | C8 | C16 | vs 0.2.4 |
|---|---:|---:|---:|---:|---:|---|
| code | **89.19** | 73.36 | 61.71 | 44.11 | 37.75 | +0.93 … +4.63% — 5/5 PASS |
| json | **85.90** | 69.28 | 54.84 | 36.70 | 31.44 | +2.41 … +6.32% — PASS/WATCH |
| structured | **76.99** | 60.41 | 51.94 | 32.79 | 27.95 | +3.48 … +38.16% — INVESTIGATE (positive) |
| prose | **51.92** | 40.06 | 29.88 | 19.51 | 15.94 | +4.49 … +6.41% — PASS/WATCH |

**Verdict: 20/20 cells positive vs the 0.2.4 baseline, zero regressions, zero hard failures.**
The four `structured` cells drift far enough positive (+16%…+38%) to be flagged INVESTIGATE;
the direction is favorable, the cause is **not identified**, and it is registered as an open
item rather than explained away (see the verdict report).

**Type ordering `code > json > structured > prose` holds at all five concurrencies** and the
spread widens with concurrency exactly as in the 0.2.4 baseline (C1 1.72× → C16 2.37×;
baseline 1.80× → 2.39×).

## Reproduction

```bash
# from the repository root; needs the 0.2.4 baseline matrix at
# data/dev3-v18-20260920/de_v3_matrix.json (shipped in this repo)
python3 data/luz028-de-sd1-20260924/compare_vs_024.py
```

`compare_vs_024.py` is fail-closed: any cell whose raw file is missing, whose `grammar` is not
`None`, whose `median_completion_tokens != 2048`, or that lost a stream, fails the run. It
reproduces the per-cell table, both type-spread tables and the verdict counts.

## Masking note

`preflight.txt` (2 occurrences) and `run.log` (1 occurrence) had the deployment root path
(`/home/<user>/dsv41-flash-dgxsparks`) replaced with `<deploy-root>`. These two files
therefore **do not match their md5 in `MANIFEST.md5`** — that manifest records the unmasked
originals as they exist on the deployment host. Masked md5s:

| file | original md5 (in `MANIFEST.md5`) | masked md5 (this copy) |
|---|---|---|
| `preflight.txt` | `0c2f61e274a096e811c938a86b295e98` | `a93ba690936c9df5e70cd4f5f8f1e4ed` |
| `run.log` | `c1e6fb173fe5984d7203732e0f42069c` | `96a5f1b6ad392df2a338fb607717da48` |

All other 22 files are byte-identical to the host copies. The archive passes
`scripts/check_redaction.py` (fail-closed leak scan).

> One honest detail visible in `preflight.txt`: the in-container identity probe returned
> `01ba4719c80b6fe9`, the well-known **false-empty constant** (`docker image inspect` run
> inside a container has no image store — the template parse error is printed right above it).
> It is recorded as it happened; it is *not* an identity. See
> [`../../BUILD-IDENTITY.md`](../../BUILD-IDENTITY.md) for the empty-input trap.