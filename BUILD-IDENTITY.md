# Build identity — what the fleet actually runs

Use this to tell whether *your* build is the same one the `[measured]` numbers in
`.env.tp4.example`, the READMEs and `docs/03-final-metrics/` came from.

**Current production: `dsv41-sglang-optimized:0.2.8` — content identity
`4cca364c46778423` (3 layers).** The download in [README §7](README.md#7-image-download-release-artifact)
is the same content; its identity is re-derivable from the archive alone.

---

## Images

| | value |
|---|---|
| Production tag | **`dsv41-sglang-optimized:0.2.8`** |
| **Content identity — the acceptance value** | **`4cca364c46778423`** = `sha256(join RootFS.Layers " ")` first 16 hex (identical on all four nodes) |
| Content identity, full | `4cca364c4677842338e65014b5c34cb353692d2cfa69bfd139f4eee086a13db2` |
| RootFS layer count | **3** (identical on all four nodes) |
| `org.dsv41.based_on` | `0.2.7` |
| `org.dsv41.built_at` (LABEL) | `2026-09-23T00:00:00Z` — pinned constant so a rebuild is byte-reproducible |
| `.Created` (real build wall clock) | `2026-09-23T09:13:55.466740698Z` |
| `org.dsv41.overlay_files` / `org.dsv41.overlay_map_md5` | `52` / `58db45c37269bf12` |
| `org.dsv41.kit_manifest_md5` | `382ad018a099946d2fd8a87dbd77d977` |
| `DSV41_IMAGE_VERSION` (env) | `0.2.8` |
| SGLang commit | `da64c5cbb8cf6bfd39be19da43573fdfd484c43a` (same commit as 0.2.4/0.2.5) |
| Registry digest | **`<none>`** — the image is built locally and shipped by `docker save` / `docker load`, never pushed to a registry |

### Lineage

| version | content identity | layers | note |
|---|---|---|---|
| 0.2.4 | `e4fe9dc13017e5d7` | 125 | last distribution before the OOM-era rebuild |
| 0.2.5 / 0.2.6 | — | — | intermediate test builds; not the current base |
| 0.2.7 | `b00ea2f8da530bd9` | 1 | **base of 0.2.8** |
| 0.2.8pre | `b177409e539ea38e` | 3 | frozen intermediate, never promoted |
| **0.2.8** | **`4cca364c46778423`** | **3** | current production; supersedes 0.2.8pre the same day |

⚠️ **The identity changes between builds by design** — every rebuild re-hashes the layer
list. The cross-version acceptance value is the *archive* content identity, not
"the identity never changes".

### Reported image IDs are not cross-node identity

`docker image inspect --format '{{.Id}}'` differs between the head node and the workers
because those are **two different objects in the same archive**: the **OCI image-index
blob** and the **image-config blob** respectively — each sha256-consistent with its own
bytes, neither describing content. The head runs the containerd snapshotter while the
workers run classic `overlay2`, and each store reports the object it keys on. Cross-node
comparison must use `content_id` (below), never `.Id` and never the layer count alone.

> ⚠️ **Do not use layer count or image ID as an acceptance criterion.** Compare the
> content identity and the build anchors below instead.

**Other images present on the hosts, NOT current:** the rollback-anchor lineage
(`dsv41-4x-spark:local`, tag reused across builds), the base `lmsysorg/sglang:dev-dsv41`,
and the `dsv41-sglang-optimized:v1…v0.2.7` lineage.

---

## Content identity — how to compute it

This is the **same formula `start.sh` uses** (`IMGID_TPL` + `img_content_id()`), so the
value is exactly what `image_preflight()` asserts across the fleet:

```bash
docker image inspect -f '{{join .RootFS.Layers " "}}' dsv41-sglang-optimized:0.2.8 \
  | sha256sum | cut -c1-16
# measured on all four nodes: 4cca364c46778423
```

> ⚠️ **The formula is byte-exact — publish it together with the value.** `docker image
> inspect -f` emits the joined layer list **with a trailing newline**, and that newline is
> part of the hashed input. Hashing the *same* 3-entry list under seven different
> serializations yields seven different 16-hex strings, all of them correct hashes of a
> real serialization of the real layer list:
>
> | hashed byte stream | sha256[:16] |
> |---|---|
> | space-joined + trailing `\n` ← **authoritative** (`{{join .RootFS.Layers " "}}` piped to `sha256sum`) | **`4cca364c46778423`** |
> | space-joined, no trailing newline | `641c82d9762eb1e6` |
> | newline-joined, no trailing newline | `ef07b58cab3784b5` |
> | newline-joined + trailing newline | `09872d95d53dba50` |
> | newline-joined + two trailing newlines | `78245b801a90b755` |
> | comma-joined + trailing newline *(governance-ledger derivation, not production)* | `e15c58f90ccd8962` |
> | newline-joined, sorted + trailing newline *(governance-ledger derivation, not production)* | `444b7a80b2701c27` |
>
> The first five were re-derived **offline from the release archive** by
> `scripts/verify_release_artifact.py`; the last two are derived values used inside the
> governance ledger and are **not** asserted by production code. Only
> `4cca364c46778423` is asserted by production, so only it is *the* identity.
> **The defect to avoid is not "hashing the wrong thing" — it is publishing a hash
> without its byte-exact pipeline**, which makes several different quantities look like
> competing claims about one quantity.

> ⚠️ **Empty-input trap (this pipeline fails *open*, not closed).** If the image is
> absent, `docker image inspect` writes nothing to stdout and exits non-zero — but the
> pipeline still prints a **well-formed-looking** hash:
>
> | input | sha256 (first 16) |
> |---|---|
> | no stdout at all | `e3b0c44298fc1c14` |
> | a single newline (what the template emits for a missing image) | `01ba4719c80b6fe9` |
>
> So `01ba4719c80b6fe9` is what a **missing** image looks like — it is *not* an identity.
> Any consumer must (a) assert image existence **before** hashing, and (b) blacklist
> both constants. `start.sh` does both (`image_preflight()` step ③).

### Additional build anchors carried by the image

These are stamped into the image config at build time and are identical on all four
nodes — useful as a second, independent check:

| label / env | value |
|---|---|
| `org.dsv41.build_version` | `0.2.8` |
| `org.dsv41.based_on` | `0.2.7` |
| `org.dsv41.built_at` | `2026-09-23T00:00:00Z` |
| `org.dsv41.overlay_files` | `52` (must equal the number of `SGLANG_OVERLAY_MAP` entries in *your* `start.sh`) |
| `org.dsv41.overlay_map_md5` | `58db45c37269bf12` |
| `org.dsv41.kit_manifest_md5` | `382ad018a099946d2fd8a87dbd77d977` |
| `SGLANG_BUILD_COMMIT` / `ai.sglang.build.commit` | `da64c5cbb8cf6bfd39be19da43573fdfd484c43a` |
| `SGLANG_IMAGE_TAG` | `lmsysorg/sglang:dev-dsv41` |
| `Entrypoint` / `Cmd` / `WorkingDir` | `["python3","-u","/opt/dsv41/boot.py"]` / `["run"]` / `/opt/dsv41` |

`start.sh`'s preflight compares `org.dsv41.overlay_files` against the local map length
and warns on mismatch — a cheap way to catch "the image was baked from a different
overlay set than this checkout".

---

## Software stack (inside the production image)

| Component | Version |
|---|---|
| SGLang | `0.0.0.dev1+gda64c5cbb` — **commit `da64c5cb`** |
| FlashInfer | `0.6.18` (`flashinfer-python`) |
| PyTorch | `2.13.0+cu130` (CUDA 13.0) |
| Grammar backend | `xgrammar` |
| Attention backend | `dsv4` (`--attention-backend dsv4`) |
| MoE runner | `flashinfer_mxfp4` |
| FP8 GEMM runner | `flashinfer_cutlass` |

**Model**: `deepseek-ai/DeepSeek-V4.1-Flash` at `/models/DeepSeek-V4.1-Flash` inside the
image. From its `config.json`: 40 layers, hidden 5120, `num_attention_heads` 64,
`num_key_value_heads` 1, `head_dim` 512, `q_lora_rank` 1280, `o_lora_rank` 1024,
384 routed experts/layer at `moe_intermediate_size` 2304 with top-6 routing plus 1
shared expert, `vocab_size` 129280, `max_position_embeddings` 1048576 (YaRN, factor 16
over a 65536 original window), expert weights `fp4` inside an `fp8` checkpoint.
Parameter count computed from this config: **≈550 B total** (543.6 B routed experts
+ 1.4 B shared + ~3.7 B attention + 1.3 B embed/head).

---

## Host stack (all four nodes identical)

| | value |
|---|---|
| GPU | NVIDIA GB10 (SM121) |
| Unified memory per node | **121.63 GiB** (Grace–Blackwell UMA: host RAM and device memory are one pool) |
| Driver | `580.173.02` |
| CUDA | 13.0 |
| Kernel | `6.17.0-1031-nvidia` |
| NCCL (host, ring-only) | `/opt/nccl-ringonly/libnccl.so.2.30.7` — **LuZ lineage**, 2.30.7 |

The NCCL is the LuZ ring-only build, *not* a sparkring patched library: it contains
neither `SWITCHLESS_RING_ONLY` nor `SKIP_TREE_CONNECT` and achieves ring-only by
disabling the Tree algorithm in NCCL's algorithm matrix (`Tree=0 / Ring=1` for all five
collectives) rather than by skipping the tree transport connect.
`scripts/nccl_selfcheck.sh` identifies which lineage a given library is.

> **UMA consequence you must know about.** Because host RAM and device memory are the
> same pool, device allocations made outside the container's cgroup are **not** visible
> to cgroup accounting, and `OOMKilled=false` is therefore *expected* even during a
> fatally over-committed run. The only precise device-side channel is
> `nvidia-smi --query-compute-apps`. Do not conclude "no OOM happened" from
> cgroup counters.
>
> A second consequence, for measurement: because the pool is shared, `eff_free`
> (`MemFree + Cached + SReclaimable − Shmem`) sits low and flat while the engine is
> resident. The 110 GiB figure the launch gate uses is a **pre-launch admission**
> threshold, not a steady-state health line. Comparing a steady-state reading against
> it produces false alarms in both directions.

---

## Runtime configuration actually in force (0.2.8 board)

The `.env.tp4` this release was boarded on (`env_md5=3f6a014d`, sanitized values):

| key | value | note |
|---|---|---|
| `IMAGE` | `dsv41-sglang-optimized:0.2.8` | production pin |
| `CONTEXT_LENGTH` | `600000` | raised from 147456 at the 0.2.8 window |
| `CHUNKED_PREFILL_SIZE` | `8192` | production and benchmark now share the same value |
| `MAX_RUNNING_REQUESTS` | `16` | concurrency ceiling |
| `MAX_TOTAL_TOKENS` | `9600000` | KV pool = 16 × 600k word |
| `MEM_FRACTION_STATIC` | `0.90` | static memory fraction |
| `SPEC_ALGO` / `DSPARK_BLOCK_SIZE` | `DSPARK` / `5` | MTP k=5 (SSE frames ≠ tokens: `tok/frame ≈5.75–5.87`) |
| `SGLANG_DSV4_KV_LAYOUT` | `fork-v4-fp4` | fp4 KV layout |
| `DSV41_PREFILL_SHARE_TOKENS` / `DSV41_PREFILL_EMPTY_CACHE_TOKENS` | `4096` / `0` | prefill share / empty-cache tiers |
| `DSV41_MOE_B12X` / `_CAPS` / `_QUANT` | `1` / `128,256,512,1024,2304,4096` / `a8` | b12x MoE backend |
| `DSV41_MXFP8_BACKEND` | `b12x` | dense MXFP8 backend |
| `DSV41_SHARED_PAD_K` | `1` | shared-expert K pad |
| `SGLANG_RAGGED_VERIFY_MODE` | `static` | upstream compact/ragged trips the V4.1 engram assert |
| `DSV41_IDX_PROTOCOL` | `1` | candidate-block protocol — **alive-switch for 256K/512K single-stream** |
| `DSV41_IDLE_RELEASE` / `DSV41_SCHED_SNAPSHOT` | `1` / `1` | OOM-era FIX-B / FIX-B' (idle release, snapshot hook) |
| `SGLANG_DSV4_PAGETABLE_PAGES_GRID` | `1` | page-table width grid OFF (deliberate, strided-window carry-over) |
| `TP_SIZE` / `EP_SIZE` / `PORT` | `4` / `2` / `8899` | tensor parallel / expert parallel / engine port |
| `NCCL_MIN_NCHANNELS` / `NCCL_MAX_NCHANNELS` | `4` / `4` | frozen baseline (both pinned) |

Engine state as reported on startup:
`max_total_num_tokens=9600000, context_len=600000, max_running_requests=16`.

`--served-model-name` is the **engine-side** name. Do not confuse it with the names
exposed by the client-facing gateway — four distinct name strings are in play (image tag,
gateway alias, engine self-report, upstream probe) and they are not interchangeable.

---

## Release artifact

| | value |
|---|---|
| File | `LuZ-0.2.8-dsv41-tp4-dgxspark.tar` (**uncompressed OCI-layout tar**) |
| Size | **14,002,663,936 bytes** (13.04 GiB) |
| MD5 | `a9d4cdf932203f173df7556aa511fee1` — recomputed over the local artifact copy, MATCH |
| SHA256 | `6c94745b261eb01a6bea9864af443d0e89583562c624926b30f9dfbc771ec3a4` |
| Produced by | `docker save dsv41-sglang-optimized:0.2.8` on the head node (containerd image store ⇒ **OCI layout**: `oci-layout` + `index.json` + `manifest.json` + `blobs/sha256/*`) |
| Tar anatomy | **14 members** = 9 blobs + `index.json` + `manifest.json` + `oci-layout` + 2 directory entries. Payload 14,002,651,431 bytes |
| Internal integrity | **all 9 blobs verified**: `sha256(bytes) == its own filename` ⇒ the archive is a self-consistent content-addressed store, nothing truncated |
| Reference closure | **0 unreferenced blobs** — every blob member is reachable from `index.json` |
| Content graph | `index.json` → OCI index `f862f816…` (855 B) → { **image manifest** `1e2779d8…` (863 B, arm64/linux, **3 layers**, config `93e7b0e3…`), docker **attestation manifest** `02036f2f…` (566 B, provenance, config `25ab58f1…`, 1 layer) } |
| Layer chain (compressed → uncompressed) | `2fb11ed2…`(14,002,048,230 B) → `be60d09e…` · `68a2b794…`(593,097 B) → `7d8f94e0…` · `4f4fb700…`(32 B, empty tar) → `5f70bf18…` — each blob's decompressed sha256 equals the config's `diff_id` |
| **Offline reproduction** | the archive **reproduces content identity `4cca364c46778423` with no cluster, no docker daemon and no GPU** — see `scripts/verify_release_artifact.py` |

> ⚠️ **Neighbouring releases are near-indistinguishable by size.** The 0.2.8 and 0.2.7
> artifacts differ by a fraction of a percent in byte count — **verify the hash, never
> judge the version by file size or file name.**

The identity is re-derivable from the artifact alone:

```bash
# .tar.zst artifacts need:  pip install zstandard
python scripts/verify_release_artifact.py LuZ-0.2.8-dsv41-tp4-dgxspark.tar --md5
# md5 MATCH · 9/9 blobs verified · 0 unreferenced
# content identity 4cca364c46778423  (full: 4cca364c4677842338e65014b5c34cb353692d2cfa69bfd139f4eee086a13db2)
# RESULT: PASS   (exit 0)
```

The script is fail-closed: a missing file, a truncated archive, an unreferenced blob, a
mismatch, or an artifact with no known expectation exits non-zero and never prints a
plausible-looking hash. The recorded run output and the full blob manifest are published
under [`data/release-artifact-20260923/`](data/release-artifact-20260923/) so the run can
be checked without re-downloading 13 GiB.

### Historical distributions

| File | Content identity | Layers |
|---|---|---|
| `LuZ-0.2.4-dsv41-tp4-dgxspark.tar.zst` (13.5 GiB, md5 `9daeb2ba314a1380988ed6f8afbe4657`) | `4ebef21b6aedbd70` | 123 |
| `LuZ-0.1.7-DSV41F-image.tar.zst` (pre-rename distribution of the same 0.2.4-era content, md5 `10307040cd70ab23436bf34eee829d24`) | `4ebef21b6aedbd70` | 123 |

Their audit records live under [`data/release-artifact-20260918/`](data/release-artifact-20260918/).
`verify_release_artifact.py` knows all three artifacts by name.

---

## Verification recipe

```bash
# 0. OFFLINE — verify the downloaded archive before loading it anywhere.
#    No cluster, no docker daemon, no GPU required.
python scripts/verify_release_artifact.py LuZ-0.2.8-dsv41-tp4-dgxspark.tar --md5
# expect: md5 MATCH · 9/9 blob sha256 verified · 0 unreferenced blobs
#         content identity 4cca364c46778423 · RESULT: PASS  (exit 0)

# 1. content identity — the single fleet-wide acceptance value.
#    Assert presence FIRST: a missing image yields 01ba4719c80b6fe9, not an error.
for h in node01 node02 node03 node04; do   # your node aliases: head + 3 workers
  echo "--- $h"
  ssh "$h" 'docker image inspect dsv41-sglang-optimized:0.2.8 >/dev/null 2>&1 || { echo "  ABSENT"; exit 0; }
            printf "  id     %s\n" "$(docker image inspect -f "{{join .RootFS.Layers \" \"}}" dsv41-sglang-optimized:0.2.8 | sha256sum | cut -c1-16)"
            printf "  layers %s\n" "$(docker image inspect -f "{{len .RootFS.Layers}}" dsv41-sglang-optimized:0.2.8)"'
done
# expect, per node: id 4cca364c46778423 / layers 3

# 2. software stack
docker run --rm --entrypoint sh dsv41-sglang-optimized:0.2.8 -c \
  'python -c "import sglang,flashinfer,torch;print(sglang.__version__,flashinfer.__version__,torch.__version__)"'
# expect: 0.0.0.dev1+gda64c5cbb 0.6.18 2.13.0+cu130

# 3. build anchors stamped into the config
docker image inspect dsv41-sglang-optimized:0.2.8 --format \
  '{{index .Config.Labels "org.dsv41.overlay_files"}} {{index .Config.Labels "org.dsv41.overlay_map_md5"}} {{index .Config.Labels "org.dsv41.built_at"}}'
# expect: 52 58db45c37269bf12 2026-09-23T00:00:00Z

# 4. NCCL lineage
scripts/nccl_selfcheck.sh
```

> Checks 0–4 are the acceptance set. **RootFS layer counts and reported image IDs are
> not** valid pass/fail criteria (see the warnings above), and an identity computation
> returning `01ba4719c80b6fe9` or `e3b0c44298fc1c14` means **the image is missing**, not
> that it mismatches.
>
> Check 0 needs nothing but the archive, so it is the one to run **first** and the only one
> a reader without cluster access can run at all. Letting a distribution be verified
> offline turns "trust the publisher's hash" into "re-derive the publisher's number",
> which is the whole point of publishing it.
