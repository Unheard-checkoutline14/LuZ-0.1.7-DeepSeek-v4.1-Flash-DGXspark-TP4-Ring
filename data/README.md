# `data/` — raw benchmark archives

Every summary number in the READMEs and in `docs/03-final-metrics/` must be
re-derivable from the files in this directory. If you find a published figure that has
no file behind it, that is a bug — please report it (see `docs/ERRATA-2026-09-18.md`
for a case where exactly this happened).

All runs below were made against the **current production form**:
600 K context · 9,600,000-token KV pool · `max_running_requests=16` · `TP4 / EP2` ·
DSpark (draft k=5 / verify=6) · fp4 indexer **enabled**. See
[`../BUILD-IDENTITY.md`](../BUILD-IDENTITY.md) for the exact image and software stack.

> ⚠️ **Provisional archives.** The benchmark toolchain is under revision: the harnesses do
> not yet share one statistics convention, so `pr-matrix-20260917/`,
> `de-freeform-20260917/` and `de-structured-20260918/` are **provisional and will be
> re-measured**. Every file here is the unmodified output of its run, and every number in
> it stays re-derivable from the file; the caveat is only about comparing *across* tables.
> `gsm8k-20260917/`, `release-artifact-20260918/` and `de-v3-20260918/` are **not**
> affected (v3 already uses the unified convention). See
> [`../benchmarks/README.md`](../benchmarks/README.md) §3 for the census, §6 for the
> scope and exit criteria of the re-run, and §7 for the v3 harness.

---

## `pr-matrix-20260917/` — prefill / decode matrix, 30 cells

6 input sizes (512, 2048, 8192, 32768, 131072, 524288 tokens) × 5 concurrencies
(1, 2, 4, 8, 16), 1024-token output budget, synthetic repeated text with unique
prefixes. **This is a throughput test, not a quality test.**

Harness: [`../benchmarks/matrix.py`](../benchmarks/matrix.py) — per-cell value is
`statistics.median`. ⚠️ **Provisional**, pending the re-run in `benchmarks/README.md` §6.

| file | content |
|---|---|
| `matrix-c1c4c16.json` | summary rows for C=1 / 4 / 16 |
| `matrix-c2c8.json` | summary rows for C=2 / 8 |
| `TOTAL-DECODE-MATRIX.md` | the same runs with a common-window "total decode" column (C=1/4/16 only) |
| `COMMON-WINDOW.md` | the shared-wall-clock interval analysis behind that column |

`summary.json` row fields: `input_tokens`, `concurrency`, `successes`,
`peak_client_overlap`, `manifest_sha256`, `effective_prefill_tps`, `median_ttft_s`,
`median_decode_tps`, `errors`.

⚠️ **Known gap (still open as of 2026-09-18).** `COMMON-WINDOW.md` and the
total-decode column of `TOTAL-DECODE-MATRIX.md` are **not** re-derivable from what is
shipped here. The tool that computes them, `benchmarks/common_window.py`, consumes
**raw per-cell request records** named `<size>-c<N>.json`; this directory ships only the
summarised arrays `matrix-c1c4c16.json` / `matrix-c2c8.json`. The raw records were not
retained. Every other column of the PR matrix *is* re-derivable. Recorded as V4 in
[`../benchmarks/README.md`](../benchmarks/README.md) §4.

- **Effective prefill** includes queueing and mixed decode work until the last request
  reaches its first token.
- **Median decode** is the per-request median over emitted tokens 129–641, including
  serving stalls.
- **`—` in the total-decode column** means the wave never had all requested streams
  decoding simultaneously. It is *not* zero throughput.
- `524288 / C=16` succeeded **10/16**: the client's 2400 s budget expired first. This is
  a client-side limit, not an engine failure, and it is reported as such everywhere.

## `de-freeform-20260917/` — decode-engine matrix, 15 cells

512-token prompt, 4096-token output budget with `ignore_eos`, three task shapes
(coding / json / prose) × five concurrencies. Single wave per cell (not a 3-wave median).

Harness: [`../benchmarks/de_matrix.py`](../benchmarks/de_matrix.py) — per-cell value is the
**upper** median `sorted(x)[n//2]`, and the prefill numerator is hardcoded `512.0`.
⚠️ **Provisional**, pending the re-run in `benchmarks/README.md` §6.

| file | content |
|---|---|
| `de_matrix.json` | the 15 summary rows |
| `de_<task>_c<N>.json` | the per-request raw records behind each row |

Row fields: `task`, `conc`, `ok`, `requested`, `prefill_tps`, `decode_tps`,
`ttft_s`, `median_ct`, `aggregate_decode_tps`. Per-request records carry
`completion_tokens`, `ttft`, `wall`, `decode_tps`, `prefill_tps`.

`decode_tps = (completion_tokens − 1) / (wall − ttft)`; `aggregate_decode_tps = decode_tps × N`.

## `de-structured-20260918/` — grammar-constrained matrix, 10 cells

Same shape as above but with a **xgrammar `json_schema`** constraint applied
(coding / json × five concurrencies), **3 waves per cell** with the median reported.

Harness: [`../benchmarks/de_matrix_structured.py`](../benchmarks/de_matrix_structured.py) —
`statistics.median`, aggregated as the median of the 3 per-wave medians. This is the third
aggregation rule in the suite, so §4/§5 are comparable to §3 only at C=1. ⚠️
**Provisional**, pending the re-run in `benchmarks/README.md` §6.

| file | content |
|---|---|
| `de_structured_matrix.json` | the 10 summary rows (adds `waves` / `ok_waves`) |
| `de_<task>_c<N>.json` | the per-wave raw records |

⚠️ Two behaviours reproduce here and are documented in the READMEs:
passing `json_schema` as a **dict** kills the engine (`TypeError: unhashable type:
'dict'` → container exit 247); and under grammar constraints `ignore_eos=True` no longer
guarantees a full token budget if the schema can terminate early.

---

## `de-v3-20260918/` — sparkDash-aligned decode matrix, 20 cells

**The corrected DE measurement** (FINAL-METRICS §4b). 4 prompt-label types
(structured / prose / code / json, prompts verbatim from sparkDash
`src/shared/llmPrompts.js`) × 5 concurrencies × 3 waves, `max_tokens=2048`,
`min_tokens=max_tokens + ignore_eos + stop=[]` force-fill, temp 0 / top_p 1 /
thinking off, **no grammar constraint of any kind**. One aggregation rule for all
cells (`statistics.median` over all ok streams of all waves), with the convention
and wave count recorded inside the JSON itself.

Harness: [`../benchmarks/de_matrix_v3.py`](../benchmarks/de_matrix_v3.py) — rationale,
root-cause analysis of the §3/§4 distortion, and the cross-channel validation against
sparkDash's own run (+0.7 %) are in [`../benchmarks/README.md`](../benchmarks/README.md) §7.

| file | content |
|---|---|
| `de_v3_matrix.json` | `_meta.protocol` + the 20 summary rows (each row carries its `convention` string) |
| `de_matrix_v3.py` | copy of the harness that produced this archive (frozen for reproducibility) |

Per-stream raw records live on the machine at
`bench-results/de-v3-20260918/de_<type>_c<N>.json` (they exceed the per-file budget
kept in this repository); the summary JSON is complete and self-describing.

| headline | value |
|---|---|
| C1 decode t/s | structured 83.0 · prose 47.4 · code 84.3 · json 78.1 |
| C16 aggregate t/s | structured 302.6 · prose 206.3 · code **562.9** · json 472.0 |
| ranking | code > json > structured > prose at every concurrency |
| cross-check vs sparkDash (`:8001`) | json C1 78.14 vs 77.59 t/s = **+0.7 %** |

---

## `gsm8k-20260917/` — the two GSM8K runs

200 questions, 8-shot CoT, temp 0.6, concurrency 1, through the `:8003` gateway.
Two rows: the 600 K production form with the fp4 indexer **off** (0.9600) and
**on** (0.535, with 92 gateway-side errors — see that directory's README for why
both the raw rate and the 107/108 among completed requests must be quoted).

Added 2026-09-18: README §2 and the metrics board publish these figures, but the
summary files were not in the repository, so the numbers had nothing behind them.

## `release-artifact-20260918/` — offline audit of the shipped image

Not a benchmark archive: this is the recorded output of `scripts/verify_release_artifact.py`
run against the distributed `LuZ-0.1.7-DSV41F-image.tar.zst` (14,463,467,578 B, md5
`10307040cd70ab23436bf34eee829d24`). It establishes, offline, that the archive is a
self-consistent content-addressed store (123/123 blobs with `sha256(bytes) == filename`),
that its reference graph closes (0 unreferenced blobs), and that it reproduces the content
identity **`4ebef21b6aedbd70`** — the value `start.sh`'s preflight asserts fleet-wide.

It is here for the same reason as the benchmark archives: a hash you cannot re-derive is a
claim, not a proof. See that directory's README for the DAG, the blob budget and the table
of all five serializations of the diffID list that have been published as "the identity".

---

## Reproducing a number

```bash
python3 - <<'PY'
import json
rows = json.load(open('pr-matrix-20260917/matrix-c1c4c16.json'))
peak = max(rows, key=lambda r: r['effective_prefill_tps'])
print(peak['input_tokens'], peak['concurrency'], round(peak['effective_prefill_tps'], 2))
PY
# -> 8192 8 3436.14
```

The summary values are the shipped ones; they were computed by the harness at run time
and re-checked independently when this documentation set was assembled.
