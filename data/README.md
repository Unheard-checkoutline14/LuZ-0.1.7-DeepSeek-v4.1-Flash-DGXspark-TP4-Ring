# `data/` — raw benchmark archives

Every summary number in the READMEs and in `docs/03-final-metrics/` must be
re-derivable from the files in this directory. If you find a published figure that has
no file behind it, that is a bug — please report it (see `docs/ERRATA-2026-09-18.md`
for a case where exactly this happened).

All runs below were made against the **current production form**:
600 K context · 9,600,000-token KV pool · `max_running_requests=16` · `TP4 / EP2` ·
DSpark (draft k=5 / verify=6) · fp4 indexer **enabled**. See
[`../BUILD-IDENTITY.md`](../BUILD-IDENTITY.md) for the exact image and software stack.

---

## `pr-matrix-20260917/` — prefill / decode matrix, 30 cells

6 input sizes (512, 2048, 8192, 32768, 131072, 524288 tokens) × 5 concurrencies
(1, 2, 4, 8, 16), 1024-token output budget, synthetic repeated text with unique
prefixes. **This is a throughput test, not a quality test.**

| file | content |
|---|---|
| `matrix-c1c4c16.json` | summary rows for C=1 / 4 / 16 |
| `matrix-c2c8.json` | summary rows for C=2 / 8 |
| `TOTAL-DECODE-MATRIX.md` | the same runs with a common-window "total decode" column (C=1/4/16 only) |
| `COMMON-WINDOW.md` | the shared-wall-clock interval analysis behind that column |

`summary.json` row fields: `input_tokens`, `concurrency`, `successes`,
`peak_client_overlap`, `manifest_sha256`, `effective_prefill_tps`, `median_ttft_s`,
`median_decode_tps`, `errors`.

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

| file | content |
|---|---|
| `de_structured_matrix.json` | the 10 summary rows (adds `waves` / `ok_waves`) |
| `de_<task>_c<N>.json` | the per-wave raw records |

⚠️ Two behaviours reproduce here and are documented in the READMEs:
passing `json_schema` as a **dict** kills the engine (`TypeError: unhashable type:
'dict'` → container exit 247); and under grammar constraints `ignore_eos=True` no longer
guarantees a full token budget if the schema can terminate early.

---

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
