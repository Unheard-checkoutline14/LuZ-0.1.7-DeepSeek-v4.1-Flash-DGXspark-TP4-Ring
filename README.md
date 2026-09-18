# LuZ-0.1.7-DSV41F · DeepSeek-V4.1-Flash on 4× DGX Spark · TP4 switchless RoCE ring

Production recipe for serving **deepseek-ai/DeepSeek-V4.1-Flash** — a ~550 B-parameter
MoE (40 layers, 384 routed experts/layer, top-6 routing + 1 shared expert, MXFP4
expert weights, 1 M native context, DSpark speculative decoding) — with **SGLang TP4
/ EP2** across **4× NVIDIA DGX Spark (GB10)** wired as a **switchless RoCE ring**
(no 400 G switch).

This repo is a **ring adaptation + operations layer + kernel overlay** on top of the
upstream SGLang recipe. It ships launcher scripts, SGLang monkey-patches / fused
decode operators, a self-heal monitor, the benchmark gate suite, and the raw
benchmark archives. **No weights, no images, no NCCL binaries.**

中文说明 → **[README.zh-CN.md](README.zh-CN.md)** · 完整部署与基准文档 → **[docs/](docs/)** ·
勘误记录 → **[docs/ERRATA-2026-09-18.md](docs/ERRATA-2026-09-18.md)**

---

## 1. What is running right now

Every number below is tagged with the **build form it was measured on**. Two forms
appear in this repo and they are *not* interchangeable — read the tag before quoting.

| | **Form A — current production** | **Form B — tuned reference (2026-09-13)** |
|---|---|---|
| context / KV pool | **600,000** / 9,600,000 tokens | 1,048,576 / 4,999,936 tokens |
| max concurrency | **16** | 12 |
| fp4 indexer | **enabled** | disabled (evaluated, then off) |
| `EP_SIZE` | 2 | 2 |
| board | §2 / §3 below | §5 below |
| full doc | [docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) | [docs/4DGX-dsv41-基准测试-横向对比-20260912.md](docs/4DGX-dsv41-基准测试-横向对比-20260912.md) |

Exact image IDs, SGLang commit, component versions and the release-artifact hashes:
**[BUILD-IDENTITY.md](BUILD-IDENTITY.md)**.
Thinking mode is written as `OFF · ON` where both were measured.

---

## 2. Form A — 600K production board (2026-09-17/18)

Measured on the running production build. **The full 30-cell PR matrix + 15-cell DE
free-form matrix + 10-cell structured matrix are in
[docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)**;
raw archives in [`data/`](data/).

| metric | value |
|---|---|
| prefill peak | **3,436.14 t/s** (8192-token input, C8) |
| prefill peak, long input | **3,403.66 t/s** (32768-token input, C4) |
| single-stream decode peak | **99.4 t/s** (coding, C1) |
| aggregate decode peak | **460.0 t/s** (prose, C16) |
| worst single-stream TTFT | **1,255.67 s** (524288-token input, C16 — 10/16 OK, client timeout) |
| GSM8K, 200 questions | **0.9600** (192/200) · temp 0.6, 8-shot |
| engine cold start | **345.7 s ≈ 5.8 min** (`tokenizer_e2e`) |

**Complete PR matrix** (6 input sizes × 5 concurrencies = 30 cells, 2026-09-17),
**effective prefill tok/s** (includes queueing and mixed decode until the last request
reaches its first token):

| Input tokens | C=1 | C=2 | C=4 | C=8 | C=16 |
|---:|---:|---:|---:|---:|---:|
| 512 | 1324.60 | 1443.17 | 2525.14 | 2896.32 | 2357.95 |
| 2048 | 2554.66 | 2970.29 | 3112.65 | 3200.83 | 3154.90 |
| 8192 | 3238.14 | 3342.89 | 3356.75 | **3436.14** | 3388.08 |
| 32768 | 3351.81 | 3259.12 | 3403.66 | 3428.73 | 3391.31 |
| 131072 | 3113.18 | 3003.73 | 3109.48 | 2951.56 | 2959.88 |
| 524288 | 2283.67 | 2248.99 | 2265.39 | 2304.64 | 2280.40 |

Per-request decode, TTFT and common-window aggregate columns are in the full doc.

**Complete DE matrix** (512-token prompt, 4096-token budget, **aggregate decode tok/s**):

| Task | C=1 | C=2 | C=4 | C=8 | C=16 |
|---|---:|---:|---:|---:|---:|
| coding | 99.4 | 136.7 | 171.6 | 213.5 | 339.0 |
| json | 77.2 | 117.3 | 159.2 | 207.7 | 336.9 |
| prose | 43.4 | 86.0 | 107.6 | 263.3 | **460.0** |
| coding *(xgrammar-constrained)* | 89.5 | 115.9 | 182.6 | 210.4 | **367.2** |
| json *(xgrammar-constrained)* | 30.2 | 66.5 | 126.2 | 183.5 | 269.8 |

**Structured output costs you at low concurrency** (coding C1: 99.4 → 89.5 tok/s,
−10.0 %) and pays back at high concurrency (coding C16: 339.0 → 367.2, +8.3 %);
json loses at every level (−19.9 % at C16). Per-cell deltas are in the full doc.

**Two structured-output traps** (both reproduced):

1. 🔴 Passing `sampling_params.json_schema` as a **dict kills the engine**
   (xgrammar `TypeError: unhashable type: 'dict'` → scheduler dies → container exit 247).
   **Always pass a JSON string.** Any caller sending a dict-shaped `response_format`
   through the serving gateway can restart the whole stack — unfixed upstream.
2. 🟠 Under grammar constraints `ignore_eos=True` stops working: if the schema can
   terminate, EOS still fires. Use constraints that cannot be satisfied early
   (e.g. `minItems`) if you need the full token budget.

---

## 3. Ring adaptation delta (vs the upstream TP4 profile)

**Transport / topology**

- Ring-only NCCL 2.30.7 + `libncclpin` core-pinning shim via `LD_PRELOAD`;
  per-rank `PEER_HCA` for the 4-edge wiring (`./start-tp4.sh ncclcheck` verifies the
  ring-only path came up). The library is the **LuZ lineage** build (ring-only via
  NCCL's algorithm matrix, `Tree=0 / Ring=1`), *not* a SparkRing patched library —
  see [BUILD-IDENTITY.md](BUILD-IDENTITY.md)
- Node-local weights (no NFS), loopback engine behind a concurrency proxy, multiple
  served-model aliases (old name kept for zero-touch consumers)

**Tuned for the ring** (each A/B'd in isolation; measured deltas in the config header)

| setting | why |
|---|---|
| `EP_SIZE=2` (was 4) | kills the expert-parallel straggler; long-context prefill 595 s → 345 s at 500 K |
| `MAX_RUNNING_REQUESTS=16` (was 12, originally 8) | with `--min-free-slots-delay 1` the upper slots actually run: c12 271 → 398 on the 12-way board; 16-way is the current production form |
| `DSV41_CACHE_GIB=1` / 16-way | Engram row cache: hit rate 0 → 99.1 %, c12 +6 %, prefill 100 K +10.5 % |
| `DSV41_SHARED_PAD_K=1` | upstream PR #17: keeps the shared expert's K=576 shape eligible for b12x (bit-identical) |
| static verify mode | upstream compact/ragged mode trips an engram target-verify assertion on V4.1 (sgl-project/sglang#39173) |

**fp4 indexer (`--enable-deepseek-v4-fp4-indexer`) is currently ON** in Form A.
It was evaluated at −6.4 % / −0.9 % / −3.3 % (c1 / c8 / c16) on 2026-09-17 and is
documented in Form B as *reverted*. Both statements are true for their own form —
the switch is env-level and reversible.

**One known regression, kept and disclosed:** c6 aggregate 260 → 236 (−9 %), an EP2
side effect; c8/c12 rise far more.

---

## 4. Experimental operator optimization (what we changed, and the risks)

The production build carries **three experimental layers** on top of upstream SGLang.
All are env-gated or file-level grafts; upstream behaviour is one flag away. They are
the main source of this build's measured gains (c12 aggregate +47 %, decode peak +12 %,
prefill 100 K +4–10 %) and the main source of its upgrade risk. Read this before
pinning a new upstream commit.

### Layer 1 — b12x CuTe kernels (fork of the b12x project, shipped in `b12x-site/`)

b12x is a consumer-Blackwell (SM120/SM121) CuTe-DSL kernel library: NVFP4/MXFP4/MXFP8
GEMM, fused MoE, paged/dense/sparse MLA attention, DSA indexing, mHC residual, PCIe
collectives. This repo vendors it under `b12x-site/` and routes selected SGLang ops
onto it:

- **MoE W4A16→b12x** (`adapter/moe_b12x.py`, gate `DSV41_MOE_B12X=1`): routes
  `flashinfer_mxfp4` MoE to b12x `fused_moe` under the replicated-input EP contract.
  Bake-off (real layer-2 weights): b12x ahead at every M (M=6 −11.4 % latency … M=2048 −5.2 %).
- **Dense MXFP8 linears→FlashInfer b12x backend** (`adapter/mxfp8_b12x.py`,
  `DSV41_MXFP8_BACKEND=b12x`): SGLang's CUTLASS SM120 kernel pads M=6→128 at decode
  (measured 50–75 GB/s, 52 ms of a 118 ms decode step); the b12x warp-level kernel
  takes small-M tiles instead.
- **Shared-expert K pad** (`adapter/shared_pad_k.py`, gate `DSV41_SHARED_PAD_K=1`):
  pads down_proj K 576→640 so the one b12x-rejected shape re-enters the fast path
  (bit-identical output; zero-block-scales encoded as 1.0).
- **MoE ladder caps** (`DSV41_MOE_B12X_CAPS=128,256,512,1024,2304,4096`,
  `DSV41_MOE_B12X_QUANT=a8`): per-bucket exact kernels up to a 96-row exactness cap,
  a8 activation quant above.

### Layer 2 — fused DeepSeek-V4 decode operators (`sglang-overlay/`)

Per-file bind-mount grafts over the image's sglang tree (see `SGLANG_OVERLAY_MAP` in
`start.sh`; the same files are baked into the production image at build time).
Headline operators, all fusing what upstream runs as separate kernels:

- `c1.py` — fused ratio-1 decode: RMSNorm + RoPE + FP4 fake-quant + FlashMLA cache write
- `c2.py` — fused ratio-2 pair-pooling decode + main-KV write (closed-form softmax;
  fp32-ulp deltas documented in-file)
- `fused_norm_rope_v2.cuh` / `main_norm_rope.cuh` / `store.cuh` / `c1.cuh` / `c2.cuh` /
  `kv_layout.cuh` — the CUDA halves of the same fusions
- `dspark_accept.py` / `dspark_draft.py` / `fast_argmax.py` / `dflash_info_v2.py` —
  DSpark speculative decode accept/draft path (two-stage split argmax, packed top-k)
- `decode_cuda_graph_runner.py`, `deepseek_v4_backend.py`, `deepseek_v2.py` —
  graph capture and backend routing
- `deepseek_v4_memory_pool.py` + `kv_cache_configurator.py` — **fork-v4-fp4 KV layout**:
  ratio-1 latents stored as FP4 (lossless vs upstream's second FP8 rounding;
  ratio-4/128 latents stay FP8)
- `dsv4_prefill_reuse.py` — adjacent prefill query rows reuse overlapping top-K sets
  (env-gated OFF by default)
- `engram.py` / `engram_hash.py` — Engram embedding row-cache integration

### Layer 3 — host-side adapters (`adapter/`)

- `engram_backend.py` + `librow_store.so` (from `row_store.cpp`) — bounded exact
  file-backed replacement for EngramEmbedding's owned-row gather (C++ extension,
  not pure Python — needs the matching image to run)
- `prefill_empty_cache.py` — returns each long-prefill chunk's transient indexer
  memory to the allocator between chunks (600 K-context headroom)

### ⚠️ Risks you accept by using this build

1. **Bit-exactness is per-path, not global.** c1/c2 use closed-form softmax and FMA
   contraction that can differ from torch by fp32 ulps; MoE `a8` mode quantizes
   activations above the exact ladder. Quality gates (GSM8K 0.9600, needle 30 K–470 K,
   corruption 0/0/0, code-gate 12/12) passed on the pinned **Form B** build — but a
   different sampling temperature or workload mix shifts the tail.
2. **Version pinning is load-bearing.** The kernels bind to the SGLang commit recorded
   in [BUILD-IDENTITY.md](BUILD-IDENTITY.md) + FlashInfer 0.6.18 +
   PyTorch 2.13.0+cu130 + driver 580.173.02. Rebase upstream and the grafts
   (esp. `deepseek_v2.py`, `deepseek_v4_backend.py`, graph runner) are the first things
   to break — `SGLANG_OVERLAY_MAP` is a shim surface, not an API.
3. **K-pad & ladder are shape-coupled.** The shared-expert pad hard-codes K=576→640;
   a different `moe_intermediate_size` or TP degree silently changes the shape and the
   pad either no-ops or misroutes. `DSV41_MOE_B12X_CAPS` likewise encodes this model's
   bucket geometry.
4. **FP4 KV layout halves per-token latent bytes.** Measured lossless for ratio-1
   latents (they are fp4-rounded upstream anyway), but it changes the memory pool
   layout — third-party pool tooling or future upstream layout changes will not read it.
5. **Graph-capture safety is on the honour system.** b12x `bind()` is written to be
   capture-safe, and `freeze_kernel_resolution` raises on a cache miss inside a live
   request — but any new shape hitting the frozen set mid-serve is a hard error,
   not a slow fallback.
6. **Documented regressions, not hidden**: c6 aggregate −9 % (EP2 side effect); 900 K
   context unavailable in the Form B configuration (Engram cache + K-pad buffer cost
   ~2 GB of deep-context headroom — 600 K and below unaffected).
7. **No upstream review.** Every file here is a local engineering artifact (r9-ops lane
   work, 2026-09-15 wave ports of upstream PRs #38409/#39370/#39420/#39187/#38979
   re-authored for this fork). Treat it as an engineering snapshot, not a
   distribution-quality patch set: audit `sglang-overlay/` against your own
   threat/perf model before reusing.

---

## 5. Form B — tuned reference board (2026-09-13)

The frozen configuration that produced the c1–c12 sweep and the context / long-prompt
results: **1 M ctx · 5 M KV pool · 12 concurrent · EP_SIZE=2 · PR#17 K-pad ·
Engram cache 1 GiB/16-way · `--min-free-slots-delay 1` · no fp4 indexer.**
Full six-stack comparison incl. LuZ / Vision-Exp / GLM:
[docs/4DGX-dsv41-基准测试-横向对比-20260912.md](docs/4DGX-dsv41-基准测试-横向对比-20260912.md).

| benchmark | value |
|---|---|
| decode peak / mean (code, temp 0) | **100.3 / 81.4** · 99.8 / 81.2 tok/s (OFF · ON) |
| prose OFF · ON | **33.3 · 36.6** tok/s |
| prefill 8 K / 32 K / 100 K | **3102 / 3443 / 3253** t/s |
| aggregate c1 / c4 / c8 / c12 | 82 / 223 / 295 / **398** tok/s (ON: 83 / 225 / 298 / 403) |
| quality gates | needle 30 K–470 K ✅ · corruption 0/0/0 · termination 18/18 + 18/18 · code-gate 12/12 · GSM8K n=50 **1.00** |
| DSpark acceptance | 3.98 tok/step, rate 0.595 (6.0 saturated on math) |
| cold start | ~9 min, **no cold-start penalty** |

**Long context** (cold prefill, needle-checked):

| depth | result |
|---|---|
| 470 K | ✅ 211.7 s · 2144 t/s |
| 600 K | ✅ 341.7 s |
| **900 K** | ⚠️ **fails** in this form — the Engram row cache and the shared-expert pad buffer cost ~2 GB of deep-context headroom. 600 K and below are unaffected. |

> The 900 K case is a **configuration capacity** limit, not engine accumulation:
> it fails on a fresh engine too.

---

## 6. Repo contents

- `start.sh / start-tp4.sh / stop.sh / boot.py` — serving orchestration, pinned
  checkpoint boot, smoke + warm-up
- `adapter/` — SGLang patches (Engram row store C++, MXFP8 backend, shared-expert
  K pad, prefill cache hook)
- `sglang-overlay/` — the fused DeepSeek-V4 decode operators grafted over the image's
  sglang tree (Layer 2 above)
- `b12x-site/` — vendored b12x CuTe-DSL kernel library (Layer 1 above)
- `scripts/` — SSH helper, `verify/` probe kit, self-heal monitor + systemd unit,
  `gate.sh`, `nccl_selfcheck.sh`, `verify_release_artifact.py` (**offline** archive
  verifier: blob integrity + content identity, no cluster needed)
- `bench/` — gate suite (needle / corruption / termination / code-gate), vision gate,
  event-timeline matrix + common-window analysis, prose, GSM8K, third-party-shaped sweep
- `data/` — **raw benchmark archives** (PR 30-cell, DE 15-cell free-form, DE 10-cell
  structured) so every summary number can be re-derived, plus the recorded offline audit
  of the release archive (`data/release-artifact-20260918/`)
- `.env.tp4.example` — the configuration this repo runs (sanitized template; the live
  `.env.tp4` is gitignored)
- `BUILD-IDENTITY.md` — image IDs, SGLang commit, component versions, artifact hashes
- `docs/` — deployment plan, upstream ISSUE/PR survey, benchmark comparison,
  final metrics board, [errata](docs/ERRATA-2026-09-18.md)

---

## 7. Image download (release artifact)

The serving image (13.5 GiB) is distributed via cloud drive:

- **Baidu Netdisk**: https://pan.baidu.com/s/1QjmmRu8GbFpWTBRkWslvBQ?pwd=luzi (extract code: `luzi`)
- **File**: `LuZ-0.1.7-DSV41F-image.tar.zst`
- **Size**: 14,463,467,578 bytes (13.5 GiB)
- **MD5**: `10307040cd70ab23436bf34eee829d24`
- **Content identity**: `4ebef21b6aedbd70` — the same value all four production nodes report, and **re-derivable offline from the archive itself**

Verify before you load anything (no cluster, no docker daemon, no GPU needed):

```bash
pip install zstandard
python scripts/verify_release_artifact.py LuZ-0.1.7-DSV41F-image.tar.zst --md5
# md5 MATCH · 123/123 blob sha256 verified · 0 unreferenced blobs
# content identity 4ebef21b6aedbd70 · RESULT: PASS  (exit 0)
```

Then load on all four nodes (all of them need the image) and re-check identity locally:

```bash
docker load -i LuZ-0.1.7-DSV41F-image.tar.zst   # requires zstd; restores dsv41-sglang-optimized:v7
docker image inspect -f '{{join .RootFS.Layers " "}}' dsv41-sglang-optimized:v7 \
  | sha256sum | cut -c1-16      # expect: 4ebef21b6aedbd70
```

That one-liner is the formula `start.sh`'s own preflight uses, so a passing local check
means the fleet-level check will pass too. **Do not** verify by layer count or by
`docker image inspect --format '{{.Id}}'`: the reported image ID differs between the head
(`03587ce9…`) and the workers (`9e1036bc…`) because those are *two different objects in
the same archive* — the OCI index blob and the image-config blob respectively — while the
123-layer content is identical. Full reasoning, all five serializations of the same layer
list that have been published as "the identity" (they hash to five different values), and
the empty-input trap (`01ba4719c80b6fe9` = a **missing** image, not an identity) are in
[BUILD-IDENTITY.md](BUILD-IDENTITY.md).

---

## 8. Sanitization and repo status

Internal IPs / hostnames are replaced with placeholders and API keys are removed
(`YOUR_API_KEY`); the site `.env.tp4` is excluded via `.gitignore`.

The repository's default branch is **`main`**, and **the adaptation lives on `main`** —
this is a standalone engineering snapshot, not a branch of the upstream project.
Upstream lineage is credited below and in [BUILD-IDENTITY.md](BUILD-IDENTITY.md).

| Component | Origin | License |
|---|---|---|
| SGLang serving recipe (boot, adapters, Engram row store, DSpark setup) | [`ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks`](https://github.com/ntxf31415/DeepSeek-v4.1-Flash-DGX-Sparks) (also published as `MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks`) | AGPL-3.0-or-later |
| Recipe lineage / benchmark methodology | [`0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000`](https://github.com/0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000) | MIT |
| Host ring-only NCCL 2.30.7 build + `libncclpin` core-pinning shim (host-side, not shipped) | [`luxingcom/aicad-nccl-optimization`](https://github.com/luxingcom/aicad-nccl-optimization) (LuZ lineage) | **no license declared** |
| Model weights | `deepseek-ai/DeepSeek-V4.1-Flash` (Hugging Face) | see model card |

**Sister projects:** [DeepSeek-V4-Flash-Vision-Exp TP4 switchless-ring](https://github.com/ntxf31415/deepseek-v4-vision-exp-dgxspark-tp4-switchless-ring) (vLLM, same ring base) · [GLM-5.3-Flash NVFP4 TP4 switchless-ring](https://github.com/ntxf31415/glm-5.3-flash-nvfp4-4x-dgx-spark-switchless) (companion recipe).
