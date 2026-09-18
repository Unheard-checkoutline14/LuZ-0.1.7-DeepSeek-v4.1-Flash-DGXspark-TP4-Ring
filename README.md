# DeepSeek-V4.1-Flash (SGLang) on 4× DGX Spark, TP4, Switchless Ring

Production recipe for serving **deepseek-ai/DeepSeek-V4.1-Flash** (552B MoE, 8B/16B
active, MXFP4 experts, 1M context, DSpark speculative decoding) with **SGLang TP4**
across **4× NVIDIA DGX Spark (GB10)** connected as a **switchless RoCE ring** (no
400G switch).

> 中文说明：[README.zh-CN.md](README.zh-CN.md) · 部署方案与基准对比：[docs/](docs/)

**Measured on 4× DGX Spark (GB10, sm_121a, switchless ring). Production now runs 600K context / 9.6M KV pool (see docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md).**

**Full 600K production board**: [docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md) — DE free-form + DE structured (xgrammar) + PR 30-cell + GSM8K 0.9600, with fp4-indexer A/B and RoCEnante verdict.
Thinking mode is given as `OFF · ON`; the build these numbers came from is pinned in
[BUILD-IDENTITY.md](BUILD-IDENTITY.md).

| benchmark | value |
|---|---|
| decode peak / mean (code, temp 0) | **100.3 / 81.4** · 99.8 / 81.2 tok/s |
| prose OFF · ON | **33.3 · 36.6** tok/s |
| prefill 8K / 32K / 100K | **3102 / 3443 / 3253** t/s |
| aggregate c1 / c4 / c8 / c12 | 82 / 223 / 295 / **398** tok/s (ON: 83 / 225 / 298 / 403) |
| quality gates | needle 30K-470K ✅ · corruption 0/0/0 · termination 18/18+18/18 · code-gate 12/12 · GSM8K n=50 **1.00** |
| DSpark acceptance | 3.98 tok/step, rate 0.595 (6.0 saturated on math) |
| cold start | ~9 min, **no cold-start penalty** |

**Long context** (cold prefill, needle-checked):

| depth | result |
|---|---|
| 470K | ✅ 211.7 s · 2144 t/s |
| 600K | ✅ 341.7 s · MemAvailable floor 4.92 GB |
| **900K** | ⚠️ **fails** — the Engram row cache and the shared-expert pad buffer cost ~2 GB of deep-context headroom. 600K and below are unaffected. |

Full six-stack comparison incl. LuZ / Vision-Exp / GLM: [docs/4DGX-dsv41-基准测试-横向对比-20260912.md](docs/4DGX-dsv41-基准测试-横向对比-20260912.md).

---

> **Sister projects:** [DeepSeek-V4-Flash-Vision-Exp TP4 switchless-ring](https://github.com/ntxf31415/deepseek-v4-vision-exp-dgxspark-tp4-switchless-ring) (vLLM, the same ring base) · [GLM-5.3-Flash NVFP4 TP4 switchless-ring](https://github.com/ntxf31415/glm-5.3-flash-nvfp4-4x-dgx-spark-switchless) (companion recipe).

## What this is

A **ring adaptation + operations layer** on top of the upstream SGLang recipe.
The repo ships launcher scripts, SGLang monkey-patches (Engram NVMe row store,
MXFP8 b12x, prefill empty-cache), a self-heal monitor, and the benchmark gate
suite. **No weights, no images, no NCCL binaries.**

| Component | Origin | License |
|---|---|---|
| SGLang serving recipe (boot, adapters, Engram row store, DSpark setup) | [MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks) | AGPL-3.0-or-later |
| Recipe lineage / benchmark methodology | [0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000](https://github.com/0xSero/deepseek-v4.1-flash-4x-rtx-pro-6000) | MIT |
| Host ring-only NCCL 2.30.7 build + `libncclpin` core-pinning shim (host-side, not shipped) | [luxingcom/aicad-nccl-optimization](https://github.com/luxingcom/aicad-nccl-optimization) (LuZ lineage) | **no license declared** |
| Model weights | `deepseek-ai/DeepSeek-V4.1-Flash` (Hugging Face) | see model card |

## Ring adaptation delta (vs upstream TP4 profile)

**Transport / topology**

- Ring-only NCCL 2.30.7 + libncclpin core-pinning shim via `LD_PRELOAD`;
  `NCCL_IB_GID_INDEX=-1` iron rule; per-rank `PEER_HCA` for the 4-edge wiring
  (`./start-tp4.sh ncclcheck` verifies the ring-only path came up). The library is
  the **LuZ lineage** build (ring-only via NCCL's algorithm matrix, `Tree=0 / Ring=1`),
  *not* a SparkRing patched library — see [BUILD-IDENTITY.md](BUILD-IDENTITY.md)
- Node-local weights (no NFS), loopback engine behind a concurrency proxy,
  multi-alias served names (old served name kept for zero-touch consumers)

**Tuned for the ring** (each A/B'd in isolation; `[measured]` deltas in the config header)

| setting | why |
|---|---|
| `EP_SIZE=2` (was 4) | kills the expert-parallel straggler; long-context prefill 595 s → 345 s at 500K |
| `MAX_RUNNING_REQUESTS=12` (was 8) | with `--min-free-slots-delay 1` the 12th slot actually runs: c12 271 → 398 |
| `DSV41_CACHE_GIB=1` / 16-way | Engram row cache: hit rate 0 → 99.1 %, c12 +6 %, prefill 100K +10.5 % |
| `DSV41_SHARED_PAD_K=1` | upstream PR #17: keeps the shared expert's K=576 shape eligible for b12x (bit-identical) |
| static verify mode | upstream compact/ragged mode trips an engram target-verify assertion on V4.1 (sgl-project/sglang#39173) |

Tried and reverted: `--enable-deepseek-v4-fp4-indexer` costs ~11 % on 500K cold
prefill and 6.4 GB of unified memory for no c12 gain. Single regression kept:
c6 260 → 236 (an EP2 side effect; c8/c12 rise far more).

## Experimental operator optimization (what we changed, and the risks)

The production build carries **three experimental layers** on top of upstream SGLang
(commit `e087e662b`). All are env-gated or file-level grafts; upstream behavior is
one flag away. They are the main source of this build's measured gains
(c12 aggregate +47%, decode peak +12%, prefill 100K +4-10% — full data in
[docs/4DGX-dsv41-基准测试-横向对比-20260912.md](docs/4DGX-dsv41-基准测试-横向对比-20260912.md)
and [docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md](docs/03-final-metrics/FINAL-METRICS-600K-2026-09-18.md)),
and the main source of its upgrade risk. Read this section before pinning a new
upstream commit.

### Layer 1 — b12x CuTe kernels (fork of the b12x project, shipped in `b12x-site/`)

b12x is a consumer-Blackwell (SM120/SM121) CuTe-DSL kernel library: NVFP4/MXFP4/MXFP8
GEMM, fused MoE, paged/dense/sparse MLA attention, DSA indexing, mHC residual, PCIe
collectives. This repo vendors it under `b12x-site/` and routes selected SGLang ops
onto it:

- **MoE W4A16→b12x** (`adapter/moe_b12x.py`, gate `DSV41_MOE_B12X=1`): routes
  `flashinfer_mxfp4` MoE to b12x `fused_moe` under the replicated-input EP contract.
  Bake-off (real layer-2 weights): b12x ahead at every M (M=6 −11.4% latency … M=2048 −5.2%).
- **Dense MXFP8 linears→FlashInfer b12x backend** (`adapter/mxfp8_b12x.py`): SGLang's
  CUTLASS SM120 kernel pads M=6→128 at decode (measured 50–75 GB/s, 52 ms of a
  118 ms decode step); the b12x warp-level kernel takes small-M tiles instead.
- **Shared-expert K pad** (`adapter/shared_pad_k.py`, gate `DSV41_SHARED_PAD_K=1`):
  pads down_proj K 576→640 so the one b12x-rejected shape re-enters the fast path
  (bit-identical output; zero-block-scales encoded as 1.0).
- **MoE ladder caps** (`DSV41_MOE_B12X_CAPS=128,…,4096`, `DSV41_MOE_B12X_QUANT=a8`):
  per-bucket exact kernels up to a 96-row exactness cap, a8 activation quant above.

### Layer 2 — fused DeepSeek-V4 decode operators (`sglang-overlay/`, 42 grafted files)

Per-file bind-mount grafts over the image's sglang tree (see `SGLANG_OVERLAY_MAP` in
`start.sh`; the same files are baked into the production image at build time).
Headline operators, all fusing what upstream runs as separate kernels:

- `c1.py` — fused ratio-1 decode: RMSNorm + RoPE + FP4 fake-quant + FlashMLA cache write
- `c2.py` — fused ratio-2 pair-pooling decode + main-KV write (closed-form softmax; fp32-ulp deltas documented in-file)
- `fused_norm_rope_v2.cuh` / `main_norm_rope.cuh` / `store.cuh` / `c1.cuh` / `c2.cuh` / `kv_layout.cuh` — the CUDA halves of the same fusions
- `dspark_accept.py` / `dspark_draft.py` / `fast_argmax.py` / `dflash_info_v2.py` — DSpark speculative decode accept/draft path (two-stage split argmax, packed top-k)
- `decode_cuda_graph_runner.py`, `deepseek_v4_backend.py`, `deepseek_v2.py` — graph capture and backend routing
- `deepseek_v4_memory_pool.py` + `kv_cache_configurator.py` — **fork-v4-fp4 KV layout**: ratio-1 latents stored as FP4 (lossless vs upstream's second FP8 rounding; ratio-4/128 latents stay FP8)
- `dsv4_prefill_reuse.py` — adjacent prefill query rows reuse overlapping top-K sets (env-gated OFF by default)
- `engram.py` / `engram_hash.py` — Engram embedding row-cache integration

### Layer 3 — host-side adapters (`adapter/`)

- `engram_backend.py` + `librow_store.so` (from `row_store.cpp`) — bounded exact
  file-backed replacement for EngramEmbedding's owned-row gather (C++ extension,
  not pure Python — needs the matching image to run)
- `prefill_empty_cache.py` — returns each long-prefill chunk's transient indexer
  memory to the allocator between chunks (600K-context headroom)

### ⚠️ Risks you accept by using this build

1. **Bit-exactness is per-path, not global.** c1/c2 use closed-form softmax and FMA
   contraction that can differ from torch by fp32 ulps; MoE `a8` mode quantizes
   activations above the exact ladder. Quality gates (GSM8K 0.9600, needle 30K–470K,
   corruption 0/0/0, code-gate 12/12) passed on the pinned build — but a different
   sampling temperature or workload mix shifts the tail.
2. **Version pinning is load-bearing.** The kernels bind to SGLang `e087e662b` +
   FlashInfer 0.6.18 + PyTorch 2.13.0+cu130 + driver 580.173.02. Rebase upstream and
   the grafts (esp. `deepseek_v2.py`, `deepseek_v4_backend.py`, graph runner) are the
   first things to break — `SGLANG_OVERLAY_MAP` is a shim surface, not an API.
3. **K-pad & ladder are shape-coupled.** The shared-expert pad hard-codes
   K=576→640; a different `moe_intermediate_size` or TP degree silently changes the
   shape and the pad either no-ops or misroutes. `DSV41_MOE_B12X_CAPS` likewise
   encodes this model's bucket geometry.
4. **FP4 KV layout halves per-token latent bytes.** Measured lossless for ratio-1
   latents (they are fp4-rounded upstream anyway), but it changes the memory pool
   layout — third-party pool tooling or future upstream layout changes will not
   read it.
5. **Graph-capture safety is on the honor system.** b12x `bind()` is written to be
   capture-safe, and freeze_kernel_resolution raises on a cache miss inside a live
   request — but any new shape hitting the frozen set mid-serve is a hard error,
   not a slow fallback.
6. **Two known regressions, documented not hidden**: c6 aggregate −9% (EP2 side
   effect) and 900K context fails (Engram cache + K-pad buffer cost ~2 GB of
   deep-context headroom; 600K and below unaffected).
7. **No upstream review.** Every file here is a local engineering artifact
   (r9-ops lane work, 2026-09-15 wave ports of upstream PRs #38409/#39370/#39420/#39187/#38979
   re-authored for this fork). Treat it as an engineering snapshot, not a
   distribution-quality patch set: audit `sglang-overlay/` against your own
   threat/perf model before reusing.

## Repo contents

- `start.sh / start-tp4.sh / stop.sh / boot.py` — serving orchestration, pinned checkpoint boot, smoke + warm-up
- `adapter/` — SGLang patches (Engram row store C++, MXFP8 backend, shared-expert K pad, prefill cache hook)
- `scripts/` — SSH helper, verify/ probe kit, self-heal monitor + systemd unit, `gate.sh`, `nccl_selfcheck.sh`
- `bench/` — gate suite (needle / corruption / termination / code-gate), vision gate, event-timeline matrix + common-window analysis, prose, GSM8K spot, third-party-shaped sweep
- `.env.tp4.example` — the configuration this repo actually runs (sanitized template; the live `.env.tp4` is gitignored)
- `BUILD-IDENTITY.md` — image IDs, SGLang commit, component versions, content md5s
- `docs/` — deployment plan, upstream ISSUE/PR survey, benchmark comparison (sanitized export)

## Image download (release artifact)

The serving image (13.5 GiB) is distributed via cloud drive:

- **Baidu Netdisk**: https://pan.baidu.com/s/1QjmmRu8GbFpWTBRkWslvBQ?pwd=luzi (extract code: `luzi`)
- **File**: `LuZ-0.1.7-DSV41F-image.tar.zst`
- **Size**: 14,463,467,578 bytes (13.5 GiB)
- **MD5**: `10307040cd70ab23436bf34eee829d24`
- **Image identity**: layers-json sha256 `e541746d26e31a3f` (must match on all 4 nodes)

Load after download (all four nodes need the image; workers = squashed 2-layer form):

```bash
docker load -i LuZ-0.1.7-DSV41F-image.tar.zst   # requires zstd; decompresses to dsv41-sglang-optimized:v7
```

## Sanitization

Internal IPs/hostnames are replaced with placeholders and API keys are removed
(`YOUR_API_KEY`); site `.env.tp4` is excluded (`.gitignore`). This fork keeps
the upstream `main` branch untouched — the adaptation lives on `4dgx-ring`.
