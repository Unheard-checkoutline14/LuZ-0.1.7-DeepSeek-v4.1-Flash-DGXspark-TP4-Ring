# RELEASE-NOTES-v0.2.8 · dsv41-sglang-optimized:0.2.8（OOM 期工程收口 + #40352 语义级回移）· 2026-09-24

> **一句话**：0.2.5 → 0.2.8 的「OOM 期工程」全部收口入库——FIX-B/B'（idle-release + 调度器快照钩子）、
> FIX-D（mqa-logits 宽度分桶）、`mm_ban`（输入侧 id 采样屏蔽）、R2（page_table 宽度网格）、
> #40352 候选块协议（语义级回移，默认关）；相对 0.2.4 **运行时代码无一件缩减（纯增量）**，
> 相对 0.2.8pre **只差默认关的 #40352 回移**。
> **PR-v3 全 40 格重测**：峰值 **5,823.11 t/s @65536×C2**；**DE SD-1 重测 20/20 格全部正向、零回归**
> （code 型 5/5 PASS）。发布件 `LuZ-0.2.8-dsv41-tp4-dgxspark.tar`（14,002,663,936 B）已随包分发，
> 内容身份 **`4cca364c46778423`** 已由归档本身离线复现。
> ops 仓提交：`b87d5d9`（#40352 语义级回移四步收口）→ `c981ed5`（0.2.8pre 身份重钉）→ 载荷与可复现构建器入库。

## 1. 构建身份

| | 值 |
|---|---|
| 镜像 | `dsv41-sglang-optimized:0.2.8` |
| **内容身份（验收值）** | **`4cca364c46778423`** = `sha256(join RootFS.Layers " ")` 前 16 位（**3 层**；四机实测全等） |
| 内容身份，全长 | `4cca364c4677842338e65014b5c34cb353692d2cfa69bfd139f4eee086a13db2` |
| 基座 | `0.2.7`（LABEL `org.dsv41.based_on`） |
| 构建墙钟（`.Created`） | `2026-09-23T09:13:55.466740698Z` |
| `org.dsv41.built_at`（LABEL） | `2026-09-23T00:00:00Z` —— 构建脚本钉成常量以保证可复现（见 §1.3），与上行是**两个不同口径** |
| `org.dsv41.overlay_files` / `overlay_map_md5` | `52` / `58db45c37269bf12` |
| `org.dsv41.kit_manifest_md5` | `382ad018a099946d2fd8a87dbd77d977` |
| SGLang | `da64c5cbb8cf6bfd39be19da43573fdfd484c43a`（与 0.2.4/0.2.5 同一 commit） |
| 定板形态指纹 | `ENV_FILE=.env.tp4`，`env_md5=3f6a014d`（全长 `3f6a014da6d025b13f769c8b31f7357d`），`chunk=8192 ctx=600000 share=4096 ec=0 golden=locked` |

### 1.1 谱系

```
0.2.4（125 层，内容身份 e4fe9dc13017e5d7）
  → 0.2.5 / 0.2.6 / 0.2.7        ← 中间测试版；0.2.7 为 0.2.8 的基座（1 层，b00ea2f8da530bd9）
  → 0.2.8pre（3 层，内容身份 b177409e539ea38e；冻结中间版本，从未晋升）
  → 0.2.8（3 层，内容身份 4cca364c46778423；同日直接取代 0.2.8pre）
```

### 1.2 0.2.8pre 与 0.2.8 的关系

**0.2.8 = 0.2.8pre 载荷 + 文档冻结 + 宿主 overlay 前移**（源码树不变）。两版在「协议关」时必然同档：
同档小格对照（`8192-c1`、`32768-c1`）两版同带。

### 1.3 两处口径注意

1. **「built」有两个值，不是一个。** 构建脚本把 `org.dsv41.built_at` 钉成常量 `2026-09-23T00:00:00Z`
   （LABEL 进 Config ⇒ 每次重建若不钉常量则身份不可复现）；镜像 `.Created` 是真实构建墙钟
   `2026-09-23T09:13:55Z`。对外引用「构建时刻」时写明用的是哪一个；两者**都不构成**
   「身份不一致」的证据。
2. **`.Id` 不是跨机身份。** 跨机比对一律用 `content_id`（= `start.sh` 预检③ 的 `img_content_id` 同口径，
   `docker image inspect -f '{{join .RootFS.Layers " "}}' | sha256sum | cut -c1-16`）。

## 2. 改动内容（文件级证据）

### 2.1 表一：0.2.4 ↔ 0.2.8 逐文件对照

| 文件 | 0.2.4 | 0.2.8 | 判词 |
|---|---|---|---|
| `forward_batch_info.py` | `99d5e0cc` | `99d5e0cc` | **逐字节相同** |
| `prefill_reuse.py` | `7c248c96` | `7c248c96` | **逐字节相同** |
| `schedule_batch.py` | `fb31d282` | `fb31d282` | **逐字节相同** |
| `candidate_indexer.py` / `dense_prefill_indexer.py` / `mqa_logits_utils.py` | — | `97cf8acc` / `8c9c007e` / `763779ca` | **新增（#40352 三件）** |
| `deepseek_v4_backend.py` | `f5d51f68` | `610eb75c` | 4823 → 5210 行 |
| `deepseek_v4.py` | `766cb0f5` | `1472fcb1` | 5269 → 5572 行 |
| `deepseek_v4_dspark.py` | `a93bb9ef` | `f1e2767c` | 1221 → 1403 行 |
| `indexer.py` | `af5c9427` | `025e4829` | 1182 → 1357 行 |
| `scheduler.py` | `b28e125a` | `3e640906` | 5731 → 5877 行 |
| `schedule_policy.py` | `c4c656cb` | `d4be0d41` | 1517 → 1596 行 |
| `flashinfer_autotune.py` | `dc56549b` | `e6f4d696` | 458 → 501 行（v14 autotune，见 §3） |
| `configurer.py` | `66ab0421` | `e2a6eac9` | 45 → 45 行 |
| `server_args.py` | `02b6c7d7` | `9c752c39` | 4502 → 4503 行 |

**计数：逐字节相同 3 件 · 净增 9 件 · 新增 3 件 ⇒ 纯增量，无一件缩减（0.2.4 的快路径全在）。**
CED 跳层与 prefill-reuse 三件（前三行）**未被 0.2.8 触碰**。

> **口径（引用前必读）**：右列（0.2.8）取自构建载荷表，并已在镜像 COPY 层内逐件复算
> 通过；左列（0.2.4）取自交付快照 `v41-sglang-delivery/sglang-overlay/`。中间版本
> （0.2.5–0.2.7）改过的文件会呈现**三个不同世代**的值 —— 见
> [§2.4](#24-运行时代码来源与逐件核对)。

### 2.2 表二：0.2.8pre ↔ 0.2.8

| 文件 | 0.2.8pre | 0.2.8 | 判词 |
|---|---|---|---|
| `deepseek_v4_backend.py` | `9e1c8fbc` | `610eb75c` | 5070 → 5210 不同 |
| `indexer.py` | `f911f984` | `025e4829` | 1289 → 1357 不同 |
| #40352 三件 | — | 三件 | **新增** |
| scheduler / schedule_policy / autotune / model / dspark / configurer / server_args | — | — | **逐字节相同（7 件）** |

⇒ **0.2.8 相对 0.2.8pre 的全部差异 = #40352 协议回移**（默认关、惰性导入，见 §3.6）。

### 2.3 载荷三组与明确排除

| 组 | 内容 | 项数 |
|---|---|---|
| ① 运行期载荷（overlay 谱系 → 镜像） | 10 件修复 + 1 件默认行为变更（`flashinfer_autotune.py`） | 11 |
| ② 仓库↔镜像一致性同步 | `gate.sh` / `boot-signature.sh` / `prv3_collector.py` | 3 |
| ③ 工具载荷 → `/opt/dsv41/kit/` | 守卫套件 + 量具 + 文档 | 46 |

> **组② 3 件的镜像内实件**（从发布 tar 的 COPY 层 `blobs/sha256/68a2b794…` 离线抽取，
> 抽取法见 §2.4「自行核对」）：`scripts/gate.sh` `c2eb49b19182007be305118950c11ad7`
> （629 行）· `scripts/boot-signature.sh` `ab3106407027ec5303db10e34bdca0b0`（180 行）·
> `benchmarks/prv3_collector.py` `bbda3e75661d25e58a7d43fb069d1674`（236 行）。
> 本仓同名文件的对照：`scripts/boot-signature.sh` 与 `bench/prv3_collector.py` 与镜像内
> **逐字节相同**；`scripts/gate.sh` 逻辑相同，唯一差异是**节点主机名按发布纪律配置化**
> （从 `.env.tp4` 的 `WORKER_HOSTS` 读、缺省为占位符，见 `scripts/check_redaction.py`
> 的 hostname 类别）——镜像内版本读不到你的集群时也须同样替换。

| 合计（构建脚本 `--check` 回执） | 运行期 14 项 + 工具 46 项 | 60 |

**明确排除**（「排除了什么」与「装了什么」同等重要）：

- `instruments/daily_smoke.py` —— 含硬编码探测密钥兜底值 ⇒ **密钥绝不进镜像**。
- `sglang-overlay/configurer.py` 回退臂 —— 回退条件「本臂恢复 ~5000 t/s」未成立
  （09-22 定谳 prefill 回归真凶与 #39482 无关）⇒ 保留原版。
- `*.bak-*` / 日志 / `state/` / `__pycache__` —— 历史与运行态，不进镜像。

### 2.4 运行时代码来源与逐件核对

**唯一事实源 = 构建脚本的两张载荷表**（`image-patches/0.2.8/build-0.2.8.sh` 的
`PAYLOAD` / `KIT_LIST`）。§2.1–§2.2 的全部哈希都应由这两张表复现；本节把它落成
**不需要集群**就能独立复算的形式。

> 📌 **该构建脚本是部署宿主上的构建对象，不随本仓分发**；本节与 §2.3 出现的
> `image-patches/…`、`instruments/…`、`state/…` 同理——保留是为了给每个数字留出处
> （provenance），**不是**让读者去找。读者侧的可核对面 = **发布 tar 本身**：按本节末尾
> 配方对 `LuZ-0.2.8-dsv41-tp4-dgxspark.tar` 离线复算，下表每个哈希都可逐件复核；
> 组② 3 件的镜像内实件 md5 亦按同法抽出，列在 §2.3 表后。

#### 0.2.8 镜像内的运行时代码（11 件）

镜像 `dsv41-sglang-optimized:0.2.8`（内容身份 `4cca364c46778423`，3 层）的运行期改动
全部落在 **COPY 层**（`blobs/sha256/68a2b794…`，593 KB）。逐件 md5：

| 容器内路径（`/sgl-workspace/sglang/python/sglang/` 之下） | md5 |
|---|---|
| `srt/layers/attention/deepseek_v4_backend.py` | `610eb75c6f12d9ac3e623c0f7508442b` |
| `srt/models/deepseek_v4.py` | `1472fcb122b24cbe2bd162ff3d12fafe` |
| `srt/models/deepseek_v4_dspark.py` | `f1e2767cf05218e80e1509ef9c7fa409` |
| `srt/layers/attention/dsv4/indexer.py` | `025e482971dfdb37c92ea92e44cb09fc` |
| `srt/layers/attention/dsv4/candidate_indexer.py` | `97cf8acce87d947a3b8770d7c0772e9c` |
| `srt/layers/attention/dsv4/dense_prefill_indexer.py` | `8c9c007e46fc93012d36a4aee1cb03ad` |
| `srt/layers/attention/mqa_logits_utils.py` | `763779caee5b594bac760015ff88a105` |
| `srt/managers/scheduler.py` | `3e64090646044b6502766b6f3933e3fd` |
| `srt/mem_cache/deepseek_v4_memory_pool.py` | `f8f1fbe197d5872f563690461d7f98b3` |
| `kernels/ops/attention/dsv4_attn_metadata_kernels.py` | `d6bbe7a6e83127b10a3706be18ff79cf` |
| `srt/model_executor/runner/flashinfer_autotune.py` | `e6f4d696f70d7426aeb2fb9a653e23ba` |

（另有 3 件组②同步载荷落在 `/opt/dsv41/` 下：`scripts/gate.sh`、`scripts/boot-signature.sh`、
`benchmarks/prv3_collector.py`。）

**自行核对**（任何机器，无需集群）：

```bash
TAR=LuZ-0.2.8-dsv41-tp4-dgxspark.tar
L=blobs/sha256/68a2b7946f478f57fddd329e7df944ad855db405579aa4cadfdaae3b428229cd
tar -xOf "$TAR" "$L" | tar -xz -C /tmp/l1 \
  sgl-workspace/sglang/python/sglang/srt/layers/attention/deepseek_v4_backend.py
md5sum /tmp/l1/sgl-workspace/sglang/python/sglang/srt/layers/attention/deepseek_v4_backend.py
# 期望 610eb75c6f12d9ac3e623c0f7508442b
```

#### 三处哈希口径，不要混用

| 口径 | 对象 | 例（`deepseek_v4_backend.py`） |
|---|---|---|
| §2.1 表「0.2.4」列 | 交付快照 `v41-sglang-delivery/sglang-overlay/`（记的是 0.2.4 世代的值） | `f5d51f68` |
| §2.1 表「0.2.8」列 = 载荷源 = **镜像 COPY 层** | 三处已实测逐字节一致 | `610eb75c` |
| 0.2.7 基座层（L0）内 | 中间版本（0.2.5–0.2.7）改过的值 | `c40a6264` |

**三者不同属正常** —— 它不是"同一文件的三个说法"，而是**三个不同世代的字节**。
由此有两条推论，引用本表时必须知道：

1. **§2.1 表的「逐字节相同」三件**（`prefill_reuse.py` / `schedule_batch.py` /
   `forward_batch_info.py`）已在 0.2.7 基座层与 0.2.8 载荷两侧实测相等 ⇒ 声明成立。
2. **`schedule_policy.py` / `configurer.py` / `server_args.py`** 在 §2.1 表里有 0.2.8 值，
   但它们**不在** 0.2.8 载荷表内 —— 其 0.2.8 值由 0.2.7 基座层继承
   （实测 `schedule_policy.py` 在基座层已是 `d4be0d41`）。改动发生在更早的中间版本，
   不是 0.2.8 干的。

#### ⚠️ 本仓 `sglang-overlay/` 与镜像不一致（已知，未修）

本仓 `sglang-overlay/`（45 件，与 `start.sh` 的 `SGLANG_OVERLAY_MAP` 一一对应）是
**开发模式（`SGLANG_CODE_MOUNTS=1`）的宿主覆盖位**，其内容截至 2026-09-24
**未与任何已发布镜像同步**。生产模式（默认 `SGLANG_CODE_MOUNTS=0`）代码**只来自镜像**，
本目录不参与；但以 `SGLANG_CODE_MOUNTS=1` 起栈会把旧字节覆盖到镜像上，而这类失效
**任何缓存检查都看不出来**。

⇒ **要核对"生产实际跑的代码"，请以镜像为准**（方法见上）。详见
[`sglang-overlay/README.md`](../../sglang-overlay/README.md)。

## 3. OOM 期工程主线（0.2.5 → 0.2.8）

事故背景：2026-09-21 四机连环 OOM 定谳 = **prefill chunk 瞬态绞死**（CUDA 缓存分配器，
~0.5–1 G/chunk，调度器记账不可见），叠加 healthcheck 磨死与 Linger 自启。0.2.8 是这批修复的收口。

### 3.1 主线一览表（含「定板生产是否在路径上」）

定板形态 = `.env.tp4`（md5 `3f6a014d`，2026-09-23 定板起栈）；「镜像缺省」指不接线时的行为。

| 项 | 门控 | 镜像缺省 | 定板生产 | 依据 |
|---|---|---|---|---|
| FIX-B idle-release | `DSV41_IDLE_RELEASE` | `0`（关） | **开（=1）** | 并入 `.env.tp4` `EXTRA_DOCKER_ENV` |
| FIX-B' SIGUSR1 快照钩子 | `DSV41_SCHED_SNAPSHOT` | `0`（关） | **开（=1，诊断）** | 同上 |
| FIX-D 宽度分桶 | **硬编码，无 env 门** | 随 fp4 indexer 分支 | **不在**（分支未开） | 无 `--enable-deepseek-v4-fp4-indexer` |
| `mm_ban` 采样屏蔽 | `DSV41_BAN_MM_PLACEHOLDERS` / `DSV41_BAN_PROMPT_CONTROL_TOKENS` | **`1`（开）** | **开（缺省即开）** | 未置 0 |
| `_run_nonpaged_rowchunk` | `SGLANG_OPT_DSV4_NONPAGED_INDEXER` | 关 | **不在** | 未置 |
| R2 page_table 网格 | `SGLANG_DSV4_PAGETABLE_PAGES_GRID` | `1024`（网格**在**） | **网格关（=1）** | 并入 `.env.tp4`（阶梯窗延续） |
| #40352 候选块协议 | `DSV41_IDX_PROTOCOL` | `false`（关） | **开（=1）** | 并入 `.env.tp4`；是 256K/512K 单流存活开关（§5） |
| v14 autotune | 无 env 门（有意晋升的默认行为变更） | 在役 | **在役** | golden digest 锁在役时两版行为一致（no-op） |

### 3.2 各项要点

- **FIX-B（idle-release）**：在 `is_fully_idle()` 安全窗内按间隔+阈值调 `torch.cuda.empty_cache()`
  释放分配器未用段；三重护栏（全闲窗 / env 门缺省关 / 低于阈值不打扰 + 心跳）。
  ⚠️ v1 曾**永不 fire**（读 `memory_stats()["reserved_bytes.all"]`，而本 torch 版键带 `.current`/`.peak`
  后缀 ⇒ `.get` 恒 0 ⇒ 无声 return）；v2 改用官方包装 `memory_reserved() - memory_allocated()` 后全链通过。
  **剂量上限 = 16K 零 NVRM 增量，32K 有 3 机擦墙** ⇒ FIX-B 只救**请求边界**，救不了请求**进行中**峰值。
- **FIX-D（mqa-logits 宽度分桶）**：把整 chunk 的 logits 分配宽度钉到闭集（16384 列的倍数），
  使同宽度类满 chunk 逐字节同尺寸 ⇒ 分配器按类复用。实测整 chunk 分配尺寸从 **9185 个互异值坍缩到 2 个**；
  reserved 段两剂剂量后 **773→777→773 零增长**。
  ⚠️ **运维禁令**：若将来启用 fp4 indexer，**必须先改分桶**（现制 2K = 1024× 冗余）。
- **`mm_ban`**：把 438 个输入侧专用 id（`129271..129278` 除外——它们是**合法**视觉 grounding 输出；
  `129264 [图像]` 的 `special=False`）在采样层置 `-inf`，target 与 draft **两侧同置**。
  **不可按区间、不可按 special 标志推导；只能显式枚举 + 与 tokenizer 对表校验。**
  边界：本补丁是**采样层过滤**，对「请求体/输入回显」类泄漏无效。
- **R2 网格**：`grid=1024` 时超过 1024 页的宽度向上取整到 1024 的倍数（消「num_pages 随上下文变宽 ⇒
  每 chunk 的 page_table 无缓存块可用」的漏网点）；网格线以下保持 legacy 精确尺寸。
  **定板形态置 `=1`（关网格）**——这是 2026-09-22 阶梯窗的延续，属有意选择。
- **#40352（语义级回移）**：不做整链回移、做语义级回移。把「每层 `[tokens, context]` fp32 ≈17 GB +
  bool 掩码 4.3 GB」改成按候选块发布 **int32 block-id 表**，消费者现算掩码、用完即弃。
  **发布物体积缩减 73.2×**（600K 角：`2048×4 B` vs `600000 B`）；候选覆盖占比 **2.73%**
  ⇒ 旧 bool 掩码 **97.27% 是纯浪费**。默认关时**零耦合**（新模块惰性导入；backend 模块级 import 面不含
  `candidate_indexer`）。CPU 等价门 **ALL PASS 42 项**（7 场景 × 4，含生产形状 600K/8192 逐元素相等）。

## 4. 性能定板数字

**口径**（不得混用）：

1. **PR（prefill）达标口径** = `Σ(prompt token) / 墙钟`（放行第一流 → 最后一流结束），
   `max_new_tokens=1`（纯 prefill，无 decode 尾巴），每请求 fresh nonce，**每格前 `POST /flush_cache`**。
2. **DE（decode）达标口径** = 每流 `(ct − 1) / (t_last − t_first)`，格中心值 = 全部有效流的
   `statistics.median`；**SD-1**（chat 通道 + 提示词标签式类型、禁 guided decoding + 强制吃满 + 每请求新 nonce）。
3. c16 **两种口径不可混用**：聚合（`Σtoken/墙钟`）与「单流中位 × N」不是同一个量。

### 4.1 PR 矩阵（40/40 格 · 全序即本仓 [`data/luz028-matrix-20260923/TABLE.md`](../../data/luz028-matrix-20260923/TABLE.md)）

窗口 `LUZ028_MATRIX4K512K_20260923T150740Z`（2026-09-23 15:07:40Z → 16:56:29Z，跑在定板 env 上），
8 档输入 × 5 档并发 = 40 格，零 VOID / 零 ABORT。**每格值均从逐流原始记录复算并与服务器 per-cell 表逐格断言相等。**

| 输入 token | C1 | C2 | C4 | C8 | C16 | 行中位 |
|---:|---:|---:|---:|---:|---:|---:|
| 4,096 | 4,464.8 | 4,480.5 | 4,530.9 | 4,875.8 | **5,033.1** | 4,530.9 |
| 8,192 | 5,360.1 | 5,337.1 | 5,165.3 | **5,383.3** | 5,326.1 | 5,337.1 |
| 16,384 | 5,498.8 | 5,638.4 | **5,639.3** | 5,618.9 | 5,494.8 | 5,618.9 |
| 32,768 | 5,772.0 | 5,781.2 | **5,810.3** | 5,691.9 | 5,689.8 | 5,772.0 |
| 65,536 | 5,792.5 | **5,823.1** | 5,777.6 | 5,701.7 | 5,724.3 | 5,777.6 |
| 131,072 | **5,791.1** | 5,671.6 | 5,620.8 | 5,600.9 | 5,675.0 | 5,671.6 |
| 262,144 | **5,585.7** | 5,429.9 | 5,439.9 | 5,496.1 | 5,520.1 | 5,496.1 |
| 524,288 | 5,042.2 | 4,976.9 | 5,009.1 | **5,066.6** | 5,038.8 | 5,038.8 |

> `4096` 行是 `NON_ALIGNED(4096 % 8192)` 半块尺寸，按本仓消费规则**不与整块行对比**，仅列完整。

**读数**：

- **全表峰值 5,823.11 t/s（65536 × C2）**；整表集中在 **4,976.9 – 5,823.1 t/s**。
- **并发不驱动吞吐**：同列（同输入档）内极差 ≤ **4.22%**；单序列最优在 65,536–131,072 档；
  长文场景「多条短 prompt」优于「少条长 prompt」（65,536 行 4,976.9–5,823.1 vs 524,288 行 4,976.9–5,066.6）。
- **512K 单流 = 5,042.18 t/s**（Σ 524,288 token ÷ 103.98 s）；单流硬门禁 `> 4500` ⇒ **+12.05% PASS**。
  **512K 全 5 档并发本轮全测**（C16 = 5,038.81，16/16 ok）——此前版本 512K 只承诺单流，本轮实测多流全部消化。
- **零 OOM、内存无退化**（8.4M token 满角后四机 `eff_free` 平稳）。

> **本矩阵与早期 v18/v19 表不可直接互比**：v18/v19 表是 512…131072 的范围且在各自的窗口；
> 0.2.8 矩阵新增 262144 / 524288 两行、并把输入构造逐格硬截断到请求 size。跨窗口对照需同工具同口径。

### 4.2 DE SD-1 重测（20/20 格 · 全序即本仓 [`data/luz028-de-sd1-20260924/`](../../data/luz028-de-sd1-20260924/)）

`RUN_TAG=LUZ028_DE_SD1_20260924`（2026-09-24T00:49:32Z → 01:43:54Z），4 类型 × 5 并发 × 3 波，
`max_tokens=2048`、全程 `grammar=None`。基线 = 0.2.4 时代 SD-1 矩阵
（[`data/dev3-v18-20260920/`](../../data/dev3-v18-20260920/)）；漂移带：≤5% PASS / 5–10% WATCH / >10% INVESTIGATE。

| 类型 | C1 | C2 | C4 | C8 | C16 | 对 0.2.4 |
|---|---:|---:|---:|---:|---:|---|
| code | **89.19** | 73.36 | 61.71 | 44.11 | 37.75 | +0.93 … +4.63% —— 5/5 PASS |
| json | **85.90** | 69.28 | 54.84 | 36.70 | 31.44 | +2.41 … +6.32% —— PASS/WATCH |
| structured | **76.99** | 60.41 | 51.94 | 32.79 | 27.95 | +3.48 … +38.16% —— INVESTIGATE（正向） |
| prose | **51.92** | 40.06 | 29.88 | 19.51 | 15.94 | +4.49 … +6.41% —— PASS/WATCH |

- **20/20 格全部正向，零回归、零硬失败**。型序 `code > json > structured > prose` 五档全成立，
  且随并发拉大极差（C1 1.72× → C16 2.37×）。
- 四格 `structured` 大正漂移（+16.11% … +38.16%）**方向有利、成因未归因**，按纪律登记为开放项
  （候选解释：MTP 投机对高可预测文本的接受率敏感等，**均未证实**）——不写成结论。

## 5. 能力轴发现：`DSV41_IDX_PROTOCOL` 是 256K/512K 单流的存活开关

**同格对照**（协议关 p0 / 协议开 p1，其余逐字相同）——判定窗口实测：

| 格子 | p0（协议关） | p1（协议开） |
|---|---|---|
| 131072-c1 | 5447.2 | 5769.0 |
| **262144-c1** | **引擎掉线（RemoteDisconnected）** | **5574.6 ✓** |
| **524288-c1** | 未跑 | 5114.7 / 5120.9 / 5114.9 ✓✓✓ |

**两条判据轴，并列报出、不可互相替代**：

| 判据轴 | 判据 | 结论 |
|---|---|---|
| **能力轴** | 256K/512K 单流是否存活/返回 200 | **协议开才通**：关 ⇒ 262144 即引擎掉线；开 ⇒ 三连全成 |
| **瞬态轴** | 512K 单流瞬态峰值增量 ≤ 3 GiB | **字面未过**（head 3.10–3.29 G；协议本身每档严格更优：32K −0.19 G、128K −1.33 G） |

两轴指向相反而不矛盾：超线是**既有项**（残差恒定不随 lc 增长），不在协议这条轴上。
**教训（已写进运维手册）**：**守卫救不了产品**——机器级地板护栏与产品级瞬态判据是两件事；
ADR-004 护栏忠实动作但 head 未破地板、引擎仍因 rank 被杀而死亡。**「护栏没响」≠「产品没问题」。**

**定板处置**：`DSV41_IDX_PROTOCOL=1` 已并入生产 `.env.tp4`（= 上述存活开关打开）。

## 6. 两次台账更正（工程教训，可复用）

### 6.1 「0.6 tok/s / 100× 回退」= 请求级读数，不是稳态性能

转产后曾观测到一次**真实但不可复现的引擎停顿**（请求级 371 s）；`≈0.6 tok/s` 是该停顿下的
**请求级 wall 读数**，不是 0.2.8 的稳态性能，也没有对应的代码变更。同窗口实测 DE 97.2 / 90.4 t/s、
PR 512K 单流 5,100+ t/s、16/16 ok、内存零退化。
**教训：区分「请求级 wall」与「稳态吞吐」——单次停顿的请求级读数不能当版本性能。**

### 6.2 「两版共有 PR −29% 缺口」= 自制探针跨 chunk 边界的伪影

真因：自制探针的 prompt 经 chat 模板成 **8215 token > 8192 = chunk 边界** ⇒ 跨 2 个 chunk，
多付一次整块流水（≈0.96 s/步）⇒ 低报 ≈1.6×。
**纪律：臂对照必须同一量具同一 prompt 构造；自造探针只可做「同探针前后对照」，跨量具比值无效。**

## 7. 已知限制与遗留

1. **FIX-D 分桶硬编码不可 env 旁路**：启用 fp4 indexer 前必须先改「下一档 ≥ lc 的 2 倍阶梯」。
2. **fp4 indexer 保持关闭**：两次 A/B 均为负（短档 −0.9…−6.4%；131072 长档开 = 慢 12%、
   统一内存多占 6.4 GB）⇒ 净亏，应 OFF。生产 `.env.tp4` 的 `EXTRA_SGLANG_ARGS` 无该 flag。
3. **FIX-B 剂量上限 = 16K**（32K 有 3 机擦墙）——只救请求边界，不救请求进行中峰值。
4. **`mm_ban` 是采样层过滤**，不覆盖「请求体/输入回显」类泄漏。
5. **`structured` 大正漂移（U-10）未归因**（§4.2）；`512K 瞬态 ≤3 GiB` 判据字面未过（§5）。
6. **每格 1 波 ⇒ PR 表无误差棒**（DE 表有 3 波误差棒）；单波读数只做同窗对照。

## 8. 发布件（release artifact）

| | 值 |
|---|---|
| 文件 | `LuZ-0.2.8-dsv41-tp4-dgxspark.tar`（**未压缩 OCI 布局 tar**，14 条目） |
| 大小 | **14,002,663,936 字节**（13.04 GiB） |
| MD5 | `a9d4cdf932203f173df7556aa511fee1` |
| SHA256 | `6c94745b261eb01a6bea9864af443d0e89583562c624926b30f9dfbc771ec3a4` |
| 内容身份 | **`4cca364c46778423`**（3 层，四机一致；**可由归档本身离线复现**） |
| 下载 | 见 [README §7](../../README.md#7-image-download-release-artifact)（双网盘通道） |
| 离线核验 | `python scripts/verify_release_artifact.py LuZ-0.2.8-dsv41-tp4-dgxspark.tar --md5 --expect-identity 4cca364c46778423 --layer-chain` |
| 审计输出留档 | [`data/release-artifact-20260923/`](../../data/release-artifact-20260923/)（md5 计时 15.6 s、完整性 19.2 s、层链 3/3） |

归档自洽性（本仓库 `data/release-artifact-20260923/` 留存完整审计输出）：
**9/9 blob `sha256(bytes) == 文件名` · 0 未引用 blob · 参考图闭合 · 身份复现 PASS**，
且**每个层 blob 解压后的 sha256 等于 config 的 `diff_id`**（主层 32,637,625,344 B）——
即「这个 tar 就是机队正在跑的那份内容」这一句是**离线可证**的，不是转述。

**配套工程报告**（发布版，脱敏后随仓库发布）：

| 报告 | 内容 |
|---|---|
| [`docs/engineering-assurance/luz028-matrix-report-pr-de-2026-09-24.md`](../engineering-assurance/luz028-matrix-report-pr-de-2026-09-24.md) | 0.2.8 完整矩阵窗（PR 40 格 + DE 20 格）的取证、复算与逐格断言记录 |
| [`docs/engineering-assurance/de-sd1-retest-verdict-2026-09-24.md`](../engineering-assurance/de-sd1-retest-verdict-2026-09-24.md) | DE SD-1 重测判决（20/20 为正、零回退；`structured` 四格 INVESTIGATE 的登记理由） |
| [`docs/engineering-assurance/interrupt-rca-image-placeholder-2026-09-24.md`](../engineering-assurance/interrupt-rca-image-placeholder-2026-09-24.md) | 服务中断 RCA：`:8001` 图像占位符 400 三连击与净化层修复（**属 §9 组件，不属本版镜像身份**；含执行事故诚实簿） |
| [`docs/engineering-assurance/rc37-prod-crossaudit-20260924.md`](../engineering-assurance/rc37-prod-crossaudit-20260924.md) | `rc3.7.1` 生产侧只读交叉审核（🟢 生产合格；P2-A fail-open 的直接验证 + 3 条非阻塞观察；**属 §9 组件**） |

> ⚠️ **相邻版本发布件的文件尺寸几乎不可分辨**（0.2.8 与 0.2.4 仅差 604,160 B／+0.0043%，
> 0.2.7 同量级 <0.005%）⇒ **取用必核哈希，禁凭大小或文件名判版本。**

## 9. 配套组件：并发代理（`gateway/`）

`gateway/` **不在镜像内容身份链路内** —— 它是宿主侧的 `:8001` 服务，随仓库源码分发、
不随 tar 分发。本节单列，避免与 §1 的镜像身份混为一谈。

自 v0.2.3 那次开源化（`92631ea`）以来，仓库内的网关源码积压了**三代未发布变更**，
本版一并补齐：

| 变更 | 说明 |
|---|---|
| **G7 图像占位符净化（默认开）** | 客户端把历史图像序列化成字面文本时，引擎编码守卫对整个请求硬 `400`、会话即死（图像字节本就不在请求里，不可复原）。网关在 `/chat/completions` 与 `/responses` 上把该字面量改写成引擎接受的纯文本，并对**无法安全净化**的 body 保持 fail-open（原样透传 ⇒ 由上游给出真实 4xx，而不是网关 500）。回退开关 `SANITIZE_IMAGE_PLACEHOLDER=0`。 |
| **非流式转发改为增量写** | `relay_plain` 由整包缓冲改为随读随写（`iter_any` + 单次写超时）。同机交替 A/B：非流式端到端劣化 **+156.4% → +4.7%**（门槛 ≤+15%），流式 −11.4%（优于直连）。 |
| rc3.4–rc3.6.1 的修复与打磨 | 逐代哈希见 [`gateway/README.md`](../../gateway/README.md) 的血缘表。 |

**口径标签（不得省）**：上述 `+156.4% → +4.7%` 是**非流式 wall 端到端**口径，与量具
[`benchmarks/gw_ab_v2.py`](../../benchmarks/gw_ab_v2.py) 的 `wall` 臂同源（该臂就是为这件事
存在的 —— **流式对照看不见整包缓冲**，因为流式客户端不是一个 read 等最后一字节）；它与流式
吞吐不是同一个量，**不可互推**。

- **等价性**：本仓库发布的 `gateway/concurrency_proxy_v2.py`（md5
  `705b746725c78b7f5e12ee0f5f199350`，722 行）与机队现役文件（md5
  `299332c1aaac5d38e7d0deb054b6869f`，754 行）**AST（剥 docstring）逐字节相同** ——
  **连版本串与日志行都无需归一化**；差异仅限注释与模块 docstring。
- 新增单测 `gateway/test_sanitize_image_placeholders.py`（15 项，含孤立代理项与深嵌套
  两条 fail-open 回归）。
- 配置面：`.env.example` 旋钮 **15 → 16**（新增 `SANITIZE_IMAGE_PLACEHOLDER`，默认 `1`）；
  systemd 样例同步补该键。
- ⚠️ **验收边界**：以上等价性与单测均为**发布件层面**的证明；生产侧上线合规由
  [`rc37-prod-crossaudit-20260924.md`](../engineering-assurance/rc37-prod-crossaudit-20260924.md)
  独立给出，两者不可互相替代。

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
> 引用本报告任意数字时，须连同 §4 的口径定义一起引用。
