# `sglang-overlay/` —— 宿主覆盖位，**不是**镜像内容

## 这个目录是什么

`start.sh` 的 `SGLANG_OVERLAY_MAP`（45 条）把本目录里的**每个文件**映射到一个
容器内路径。它只在**开发模式**下生效：

| 模式 | 开关 | 代码来源 |
|---|---|---|
| **生产**（默认） | `SGLANG_CODE_MOUNTS=0` | **只来自镜像** —— 本目录完全不参与 |
| 开发 | `SGLANG_CODE_MOUNTS=1` | 逐文件 `-v` 覆盖镜像内同名文件（改完重启即可，不必重建镜像） |

```bash
# 挂载点（start.sh sglang_overlay_mounts()）
-v "$SGLANG_OVERLAY_DIR/<本目录文件>:/sgl-workspace/sglang/<映射目标>:ro"
```

⚠️ **生产起栈必须用 `SGLANG_CODE_MOUNTS=0`**（默认值）。`start.sh` 在缺镜像时会提示
"或临时 `SGLANG_CODE_MOUNTS=1` 走宿主代码" —— 那是**应急通路**，不是部署方式。

---

## ⚠️ 同步状态（截至 2026-09-24）

**本目录的内容尚未与任何已发布镜像逐字节对齐。** 实测证据：

| 文件 | 本目录 md5(前8) | 0.2.8 镜像内 | 0.2.7 基座层内 |
|---|---|---|---|
| `deepseek_v4_backend.py` | `4c8fd17b` | `610eb75c` | `c40a6264` |
| `deepseek_v4_model.py` | `6bce99ce` | `1472fcb1` | `766cb0f5` |
| `deepseek_v4_dspark.py` | `866aaa61` | `f1e2767c` | `a93bb9ef` |
| `dsv4_indexer.py` | `8ed43db1` | `025e4829` | `af5c9427` |

三者互不相等 ⇒ 本目录既不是 0.2.8 载荷、也不是 0.2.7 基座。

**后果**：以 `SGLANG_CODE_MOUNTS=1` 起栈会把**旧代码**覆盖到镜像上，
且这类失效**任何缓存检查都看不出来**（`start.sh` 原话：逐文件 bind-mount 钉住 inode）。

⇒ **要核对"生产实际跑的代码"，请以镜像为准，不要以本目录为准。**

---

## 0.2.8 镜像内的运行时代码（权威清单）

镜像 `dsv41-sglang-optimized:0.2.8`（内容身份 `4cca364c46778423`，3 层）的
运行时代码由构建载荷表写入，落在两层：基座层 + COPY 层。**COPY 层（`68a2b794…`,
593 KB）即 0.2.8 的全部运行期改动**，共 11 件：

| 容器内路径（`/sgl-workspace/sglang/python/sglang/…`） | md5 |
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

> 第 11 件（`flashinfer_autotune.py`）是本次**唯一有意晋升的默认行为变更**（v14 autotune
> 多数表决），其余 10 件是运行期修复与 #40352 协议回移。逐件判词见
> [RELEASE-NOTES-v0.2.8 §2](../docs/release-notes/RELEASE-NOTES-v0.2.8.md)。

---

## 怎么自己核对（不需要集群）

`LuZ-0.2.8-dsv41-tp4-dgxspark.tar` 是 OCI 布局的 `docker save` 产物，COPY 层可在
**任何机器**上抽出并逐件比对：

```bash
TAR=LuZ-0.2.8-dsv41-tp4-dgxspark.tar
COPY_LAYER=blobs/sha256/68a2b7946f478f57fddd329e7df944ad855db405579aa4cadfdaae3b428229cd   # 593 KB

# 1) 确认这层就是 0.2.8 的运行期载荷（应列出 11 个 .py + kit/ 工具载荷）
tar -xOf "$TAR" "$COPY_LAYER" | tar -tz | grep '\.py$'

# 2) 抽出并逐件算 md5，与上表对照
tar -xOf "$TAR" "$COPY_LAYER" | tar -xz -C /tmp/l1 \
  sgl-workspace/sglang/python/sglang/srt/layers/attention/deepseek_v4_backend.py
md5sum /tmp/l1/sgl-workspace/sglang/python/sglang/srt/layers/attention/deepseek_v4_backend.py
# 期望：610eb75c6f12d9ac3e623c0f7508442b
```

镜像级的完整性校验（9/9 blob 的 `sha256(bytes) == 文件名`、层链 `diff_id` 闭合）用：

```bash
python scripts/verify_release_artifact.py "$TAR" --md5 --expect-identity 4cca364c46778423 --layer-chain
```

> 本目录的 md5 与上表**不一致是预期的**（见"同步状态"）。若你看到一致，
> 说明同步已完成 —— 请更新本节。

---

## 目录清洁度

- `decode_cuda_graph_runner.py.orig` —— 合并冲突备份，**不应在发布仓内**，随本轮修正删除。
- `__pycache__/` —— Python 字节码缓存，不属于源码，随本轮修正删除。
- `roce_batch_result_processor.py` / `roce_parallel_state.py` / `roce_pynccl.py` ——
  **不在** `SGLANG_OVERLAY_MAP` 内，即开发模式下**不会被挂载**；保留作为参考实现。
