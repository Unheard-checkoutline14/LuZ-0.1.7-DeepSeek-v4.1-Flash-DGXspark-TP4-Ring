# `benchmarks/` — the harnesses behind the published numbers

Every figure in `README.md` §2 and in `docs/03-final-metrics/` was produced by one of
the files in this directory or in `bench/`. This directory holds the ones that shape a
*row* of a published table; `bench/` holds the quality gates and the ad-hoc probes.

If you want to re-derive a number rather than trust it, start here and in
[`../data/README.md`](../data/README.md).

---

## 1. Which harness produced which archive

| harness | what it measures | archive it produces | published in |
|---|---|---|---|
| `matrix.py` | prefill/decode matrix, 6 input sizes × 5 concurrencies; `effective_prefill_tps`, `median_ttft_s`, `median_decode_tps`, `peak_client_overlap` | `data/pr-matrix-20260917/` (30 cells) | README §2, FINAL-METRICS §2 |
| `de_matrix.py` | decode-throughput matrix, 3 task shapes × 5 concurrencies, **free-form** (no grammar) | `data/de-freeform-20260917/` (15 cells) | README §2, §3 |
| `de_matrix_structured.py` | same, but **xgrammar `json_schema`-constrained**, coding/json × 5 concurrencies, 3 waves per cell | `data/de-structured-20260918/` (10 cells) | FINAL-METRICS §4, §5 |
| `code256_bench.py` | fixed 256-token code prompt at C=1/8/16 — the fp4-indexer A/B | (stdout only; deltas in §7) | FINAL-METRICS §7 |
| `pr_ab_gw_vs_direct.py` | identical long prompt through the `:8001` gateway vs straight to `:8899`, alternating order | (stdout only) | FINAL-METRICS §9 |
| `common_window.py` | re-analysis: delivered throughput while every stream in a wave overlaps | `data/pr-matrix-20260917/COMMON-WINDOW.md`, `TOTAL-DECODE-MATRIX.md` | README §2 |
| `sweep.py` | streaming sweep emitting token IDs, for common-window evidence | — | — |
| `../bench/gsm8k_dsv41.py` | GSM8K, 200 questions, 8-shot CoT, temp 0.6 | `data/gsm8k-20260917/` | README §2, FINAL-METRICS §6 |

`bench/` (quality gates, not tables): `gates_suite.py` (needle gradient / Hangul
corruption / termination / code gate), `vision_gate.py` (both-direction red/blue
image check), `prose_bench.py`, `bench_tp.py` (third-party-shaped sweep),
`moe_a8_*` + `moe_bakeoff.py` (kernel-level numerics and capacity ladders),
`matrix_v1.py` (the earlier `/v1`-shaped implementation of `matrix.py`).

---

## 2. Running them

Each harness talks to a live engine over loopback; none of them need a cluster
scheduler, and none of them start or stop containers.

```bash
# engine on 127.0.0.1:8899, key in a one-line file (default /state/api-key)
export KEY_FILE=/state/api-key
export CONCURRENCIES=1,2,4,8,16
export OUT_DIR=/tmp/de-out
python3 benchmarks/de_matrix.py
```

| harness | env | notes |
|---|---|---|
| `matrix.py` | `MODEL_PATH`, `STATE_PATH`, `MANIFEST_PATH`, `PREFILL_SIZES`, `CONCURRENCIES` | needs `tokenizers` and the model's `encoding/` module; reads the key from `<STATE_PATH>/api-key` |
| `de_matrix.py` | `KEY_FILE`, `CONCURRENCIES`, `OUT_DIR` | |
| `de_matrix_structured.py` | `KEY_FILE`, `CONCURRENCIES`, `WAVES`, `OUT_DIR` | `key` is read from the file; the **value** is never in the repo |
| `code256_bench.py` | `KEY_FILE` | |
| `pr_ab_gw_vs_direct.py` | `AB_GW_KEY`, `AB_DIRECT_KEY`, `AB_MODEL_CANDIDATES` | refuses to start unless both keys are set |
| `common_window.py` | — | `python3 common_window.py <folder-of-raw-records>` |

**Provisioning.** Two credentials sit behind the `:8001` / `:8899` hops. They are
supplied through the environment or through the serving `.env`
(see `../.env.tp4.example`); they are not, and must not be, in this tree.

**Model names.** Four different model-name strings are in play across this stack
(image tag, gateway alias, engine self-report, upstream probe), and they are *not*
interchangeable. `pr_ab_gw_vs_direct.py` discovers an acceptable name by preflight
instead of hardcoding one.

---

## 3. Statistics conventions — two that genuinely differ

The two DE harnesses do **not** compute the same statistic. This is deliberate
fidelity, not an oversight: both are kept exactly as they were when the archives
were produced, because changing either would make the shipped JSON no longer
reproducible from the file.

| | `de_matrix.py` (free-form) | `de_matrix_structured.py` (constrained) |
|---|---|---|
| per-cell central value | `sorted(x)[n // 2]` — **upper** median | `statistics.median` — mean of the two middles for even n |
| prefill numerator | hardcoded `512.0` | real `prompt_tokens` from `meta_info` |
| waves per cell | 1 | 3, then median-of-wave-medians |
| per-request grouping | single wave | per-wave medians first |

Consequences to be aware of when comparing across the two tables:

- At C=1 they agree. At **even** concurrency they can differ by one order statistic.
- The **structured-vs-free-form deltas** in FINAL-METRICS §5 (e.g. coding C1
  99.4 → 89.5, −10.0 %) cross this boundary. The direction and rough size are
  robust; the last decimal is not comparable across the two harnesses.

`code256_bench.py` follows the `de_matrix.py` convention (upper median).

Recorded as errata row **52** in
[`../docs/ERRATA-2026-09-18.md`](../docs/ERRATA-2026-09-18.md) and as **V2** in §4 below.
It was left as-is on purpose: correcting either harness would make the archive it
produced non-reproducible from its own file, which is the worse defect.

---

## 4. Verification pass — 2026-09-18

Everything in this directory, plus `bench/`, `scripts/verify/` and `tests/`, was
audited on 2026-09-18. Findings, including the ones that are still open:

| # | finding | status |
|---|---|---|
| V1 | `scripts/dsv41-monitor-head.sh:29` had `for h in <WIP_R1> <WIP_R2> <WIP_R3>` — angle-bracket placeholders in **command position**, which is a hard bash syntax error. The published script could not run at all. | **fixed** — now `_PH_HEAD_IP_.187/188/189`, overridable via `WORKER_IPS` |
| V2 | The two DE harnesses disagree on median convention and prefill numerator (§3 above). | documented, **not changed** — changing it would break reproduction of the shipped archives |
| V3 | README §2 publishes GSM8K **0.9600** and FINAL-METRICS §6 cites `bench-results/gsm8k-600k.summary.json`, but no such file was in `data/` — the number had no file behind it, which `data/README.md` itself calls a bug. | **fixed** — `data/gsm8k-20260917/` |
| V4 | `data/pr-matrix-20260917/COMMON-WINDOW.md` and its `TOTAL-DECODE-MATRIX.md` column are **not re-derivable** from the shipped archive: `common_window.py` consumes raw per-cell records named `<size>-c<N>.json`, and the archive ships only the summary arrays `matrix-c1c4c16.json` / `matrix-c2c8.json`. | **open** — needs the raw records, which were not retained |
| V5 | `scripts/dsv41-park-guard.sh:9` assigns `ts=<unix-seconds>` and never uses it; line 10 renames to the literal `dsv41-parkold-`, while the header comment promises `dsv41-parkold-<ts>`. After the first rotation the rename target already exists, so `docker rename` fails, `&&` short-circuits, and the guard stops creating new holders. | **open, reported** — not fixed, because the intended form of the timestamp is not recoverable and guessing would change behaviour |
| V6 | Syntax: all 27 `.py` files under `bench/`, `benchmarks/`, `scripts/`, `tests/` compile; all 9 `.sh` files pass `bash -n` **after** the V1 fix. Before it, 8/9 passed. | verified |

Sanitization: the four harnesses added on 2026-09-18 were re-derived from the
private working copies with an independent, fail-closed scanner
(27 must-fire / 16 must-silent patterns, self-tested before use). One of them
originally carried two live API keys and an internal IP address in plaintext;
those are now environment variables with no defaults, and the file refuses to run
without them.

---

## 5. What is deliberately not here

- **Engine logs and raw per-request traces** for runs already summarised — only the
  summaries were retained. V4 above is the one place where this bites a published
  number.
- **The `.env.tp4` actually in use** — gitignored; `../.env.tp4.example` is the
  sanitized template.
- **The RoCE one-shot RDMA work** (FINAL-METRICS §8) — the verdict was "rejected and
  rolled back"; its scripts were left on the machines on purpose and are not part of
  this distribution.
