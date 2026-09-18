# `benchmarks/` — the harnesses behind the published numbers

> ⚠️ **Benchmark toolchain under revision — the PR and DE tables are provisional.**
> The harnesses in this directory do not yet share a single statistics convention
> (§3), so the PR and DE figures published today are marked provisional and **will be
> re-measured** once the convention is settled. Nothing is retracted: every published
> value is the value its harness computed at run time, and every value is still
> re-derivable from the archive named against it. What is not yet true is that the
> numbers across tables are computed by one rule. §6 states what is affected, what the
> revision has to settle, and what has to happen before this notice comes down.

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

⚠️ Four rows in the table above — `matrix.py`, `de_matrix.py`,
`de_matrix_structured.py`, `code256_bench.py` — are **provisional**. Their figures are
being re-measured under the revision in §6, because those are the harnesses that do not
share one statistics rule (§3). `common_window.py`, `sweep.py`, `pr_ab_gw_vs_direct.py`
and `gsm8k_dsv41.py` are not affected.

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

## 3. Statistics conventions — a full census, and why the tables are provisional

Every harness that shapes a published row was read directly and its aggregation rule
recorded. There are **three** aggregation rules in use, not two, plus **three**
different prefill numerators. Nothing in the suite is wrong on its own terms; the
problem is that they are not the same rule, so a number may not be compared across
tables without saying which harness produced it.

| harness | archive / table it produced | per-cell central value | prefill numerator | waves |
|---|---|---|---|---|
| `de_matrix.py` | `data/de-freeform-20260917/` → FINAL-METRICS §3 | upper median `sorted(x)[n//2]` | hardcoded `512.0` | 1 |
| `de_matrix_structured.py` | `data/de-structured-20260918/` → §4 | median of per-wave medians | real `prompt_tokens` | 3 |
| `matrix.py` | `data/pr-matrix-20260917/` → §2 | `statistics.median` | `size × N / wall` (aggregate burst) | 1 |
| `common_window.py` | `COMMON-WINDOW.md` column | `statistics.median` | — | — |
| `code256_bench.py` | the fp4-indexer A/B → §7 | upper median `sorted(x)[n//2]` | — | 1 |
| `pr_ab_gw_vs_direct.py` | gateway-vs-direct → §9 | ratio of two totals | real `usage.prompt_tokens` | 1 |
| `bench/prose_bench.py`, `bench/bench_tp.py` | Form B board (§5) | `statistics.median` | — | — |

Two things this census settles, both of which would otherwise be "fixed" wrongly:

- **`512/(right − left)` in `matrix.py:69` and `sweep.py:62` is not the same animal.**
  That `512` is the *token count of the 129–641 window* (641 − 129 = 512 tokens) divided
  by the window duration. It is a fixed physical window, correctly hardcoded. Only
  `de_matrix.py`'s `512.0` is a *prompt-length* numerator, and only there is it an
  approximation of a value the engine actually reports. Do not change the window one.
- **The structured harness's 3-wave rule is a different measurement, not just a
  different statistic.** It averages per-wave medians to report steady state; the
  free-form harness reports a single wave. Unifying the *statistic* must not flatten the
  *wave count* — that would silently change what §4/§5 are measuring.

Where the two DE harnesses differ, in detail:

| | `de_matrix.py` (free-form) | `de_matrix_structured.py` (constrained) |
|---|---|---|
| per-cell central value | `sorted(x)[n // 2]` — **upper** median | `statistics.median` — mean of the two middles for even n |
| prefill numerator | hardcoded `512.0` | real `prompt_tokens` from `meta_info` |
| waves per cell | 1 | 3, then median-of-wave-medians |
| per-request grouping | single wave | per-wave medians first |

Consequences to be aware of when comparing across the two tables:

- At C=1 they agree. At **even** concurrency they can differ by one order statistic.
  DE is measured at C = 1, 2, 4, 8, 16, so four of five concurrency levels are exposed;
  only the C=1 column is unaffected.
- The **structured-vs-free-form deltas** in FINAL-METRICS §5 (e.g. coding C1
  99.4 → 89.5, −10.0 %) cross this boundary. The direction and rough size are
  robust; the last decimal is not comparable across the two harnesses.
- `matrix.py` (the PR board) already uses `statistics.median`, so the PR table is
  internally consistent. It is included in the re-run for a different reason: the
  revision may change the convention, and the PR board is the reference the others are
  read against.

Recorded as errata row **52** in
[`../docs/ERRATA-2026-09-18.md`](../docs/ERRATA-2026-09-18.md), extended by row **53**,
and as **V2** in §4 below. Both DE harnesses are kept exactly as they were when their
archives were produced — changing either would make the shipped JSON non-reproducible
from its own file, which is the worse defect. The revision therefore happens by
**re-running**, not by editing the history.

---

## 4. Verification pass — 2026-09-18

Everything in this directory, plus `bench/`, `scripts/verify/` and `tests/`, was
audited on 2026-09-18. Findings, including the ones that are still open:

| # | finding | status |
|---|---|---|
| V1 | `scripts/dsv41-monitor-head.sh:29` had `for h in <WIP_R1> <WIP_R2> <WIP_R3>` — angle-bracket placeholders in **command position**, which is a hard bash syntax error. The published script could not run at all. | **fixed** — now `_PH_HEAD_IP_.187/188/189`, overridable via `WORKER_IPS` |
| V2 | The harnesses in this directory do not share one statistics convention. The 2026-09-18 census found **three** aggregation rules and **three** prefill numerators in use (§3 above). | **escalated** — resolved by re-running rather than by editing either harness; scope and exit criteria in §6 |
| V7 | The fp4-indexer A/B in FINAL-METRICS §7 is produced by `code256_bench.py`, which uses the same upper-median rule as `de_matrix.py`. That table is therefore exposed to the same revision as the DE free-form matrix. | **provisional, pending re-run** — see §6 |
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

### 4.1 Scan hits that are benign — please do not "fix" these

The same scan reports hits in pre-existing files. Every one was classified by hand,
and all of them are benign. They are listed here so that a future pass does not
spend time on them, and — more importantly — does not "clean" something that is
load-bearing:

| hit | where | why it stays |
|---|---|---|
| `10.0.0.x` addresses | `.env.example`, `.env.tp4.example`, `stop.sh`, `scripts/verify/*.py`, `files/nfs-share.sh` | the repository's own generic scheme: `10.0.0.1` = head, `10.0.0.2` = worker 1. Used consistently across seven files; the real fabric is a different range entirely |
| `10.0.22.x` / `10.0.23.x` / `10.0.33.x` | same files | part of that same generic scheme (NFS pairs), not the fabric |
| `zurih` | `scripts/verify/ramp2.sh`, `.env.tp4.example` | **upstream author identifier**, not a credential. It appears in the upstream `NOTICE`/copyright lines. Removing it would strip attribution |
| `?pwd=luzi` | `README.md` §7 | a deliberately published cloud-drive extract code — it is *how* the reader is meant to get the image |
| `/opt/aicad-prod` | `start.sh`, `deployment plan 09-11` | `aicad` is a **published** project name: README's attribution table already links `github.com/luxingcom/aicad-nccl-optimization` as the origin of the `libncclpin` shim. The path reveals nothing not already credited |
| `~189 GiB` | `boot.py:281` | a memory *size*, matching an address-shaped pattern by coincidence |
| `149.8 / 140.3 tok/s` | research reports | throughput pairs; the second value matches a ring-host-octet pattern by coincidence |
| `disk-cache-hit`, `mask-initialization` | `b12x-site/` | matched an `sk-` key pattern mid-word; a left word boundary excludes them |
| `API_KEY = "YOUR_API_KEY"` | `bench/gsm8k_dsv41.py`, `scripts/verify/*` | already the intended public placeholder |
| `password = os.environ.get("WORKER_PASS")` | `scripts/remote.py` | a variable *reference*, not a literal |

The two categories that caused real false positives in the first pass were
**numeric coincidence** (a throughput figure shaped like an address fragment) and
**mid-word substring matches** — the string `disk-cache-hit` contains the three
characters a naive key pattern reads as a key prefix, so the scanning pattern is
anchored to a token boundary rather than left free to match mid-word. Both are pinned
as regression cases in the scanner's self-test.

> A trap worth recording, because this paragraph walked into it: an earlier draft
> abbreviated the example by eliding its middle with a Unicode ellipsis, and that
> **reintroduced the exact false positive it was describing**. The ellipsis is not a word
> character, so the boundary anchor no longer applied and the abbreviated example fired
> the very rule it was warning about. Documentation that quotes a pattern is executable
> as far as the pattern is concerned.

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

---

## 6. Toolchain revision in progress — the PR and DE tables will be re-run

**Status: open. Decision taken 2026-09-18.** The benchmark toolchain is being revised
because the census in §3 showed the suite computes its central values by three different
rules. Once the revision lands, the **PR matrix and both DE matrices are re-run** so that
every published row comes from one convention and one frozen build form.

### What is provisional today

| table | harness | why it is on the list |
|---|---|---|
| FINAL-METRICS §3, DE free-form (15 cells) | `de_matrix.py` | upper median + hardcoded `512.0` numerator |
| FINAL-METRICS §4/§5, DE structured (10 cells) | `de_matrix_structured.py` | third convention (median-of-wave-medians); comparable to §3 only at C=1 |
| FINAL-METRICS §7, fp4-indexer A/B | `code256_bench.py` | upper median (see V7) |
| FINAL-METRICS §2, PR matrix (30 cells) | `matrix.py` | already true-median, but it is the reference the above are read against, and the revision may move the convention under it |

The figures in these tables are **not wrong and not withdrawn**: each is the value its
harness produced, and each is still re-derivable from its archive. Treat any figure
quoted from them as *provisional*, and quote the harness alongside it.

### What the revision has to settle

1. **One per-cell central value rule.** The recommendation is `statistics.median`
   (the true median), because four of the six row-producing harnesses already use it and
   the upper median biases every even-concurrency cell by one order statistic. This is a
   proposal, not yet a decision.
2. **Wave count is a separate knob, and must stay explicit.** `de_matrix_structured.py`
   reports a 3-wave steady state; `de_matrix.py` reports one wave. Unifying the statistic
   must not silently flatten this — the re-run should record the wave count *in the JSON*
   rather than leave it implied by which file was run.
3. **One prefill numerator, named in the output.** `512.0` / `prompt_tokens` /
   `size × N / wall` are three different quantities. Whichever is kept, the emitted row
   should say which one it is, so a future reader cannot compare two tables that measure
   different things.
4. **Retain the raw per-cell records this time.** Closes **V4**: the revision is the
   occasion to keep the `<size>-c<N>.json` records that `common_window.py` consumes, so
   that the common-window column stops being the one column with no path back to its
   inputs.

### What has to happen before this notice comes down

- [ ] A convention is selected and implemented in every harness that emits a published row.
- [ ] The convention and the wave count are written **into the emitted JSON**, not only
      into these docs.
- [ ] PR (30 cells) + DE free-form (15) + DE structured (10) + fp4-indexer A/B are re-run
      **in one authorised window, against one frozen build form**.
- [ ] New archives land in `../data/`; the superseded archives are **kept**, renamed with a
      `superseded-` prefix and a pointer, never deleted — the old numbers stay auditable.
- [ ] Errata rows 52/53 are closed with a pointer to the re-run archives, and this banner
      and §6 are removed.

The re-run needs a cluster window and an OOM-safe restart on a form that duplicates
production; **this repository only carries the request, the harnesses and the archives**,
never the run itself. The request is stated in the project's engineering-assurance
deliverables.
