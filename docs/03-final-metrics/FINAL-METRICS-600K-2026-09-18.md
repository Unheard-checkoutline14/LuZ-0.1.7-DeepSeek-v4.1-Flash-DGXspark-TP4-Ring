# FINAL-METRICS-600K · DeepSeek-V4.1-Flash · 4× DGX Spark TP4 Ring

> 状态行（内容一变，此号必递增）：**Rev.1.0 · 2026-09-18**（结构化 DE 重测补录；自引用指标不登记）

## §0 测试口径

- 引擎：SGLang（fork，DSpark MTP k=5，verify=6）· 4× DGX Spark GB10/sm_121a · switchless RoCE ring · TP4/EP2
- 生产参数：`max_model_len=600000`（600K 在役）· `mem_fraction_static=0.9` · `max_total_tokens=9600000` · `max_running_requests=16` · KV `fp8_e4m3`
- 口径对齐 LuZ0.4.5 板书（FINAL-METRICS-2026-09-02）：uuid 冷前缀、每请求 p50 中位、
  prefill = prompt_tokens/TTFT、decode = (ct−1)/(wall−TTFT)、总吞吐 = 每请求 × N
- DE：512 输入 + 4096 `ignore_eos`；PR：512/2048/…/524288 输入 × C1/2/4/8/16
- **fp4-indexer 已开**（`--enable-deepseek-v4-fp4-indexer`）；RoCEnante one-shot RDMA 已评估并**否决**（见 §8）

## §1 TL;DR

| 指标 | 结果 |
|---|---|
| prefill 峰值 | **3,352 tps**（PR32768-C1） |
| 总 PR 峰值 | **6,319 tps**（PR32768-C16） |
| 总 DE 峰值 | **358.6 t/s**（prose-C16） |
| GSM8K（200 题 greedy） | **0.9600**（192/200） |
| 524288-C16 | 10/16 成功（客户端 2400s 超时，非引擎故障，如实标注） |

## §2 DE 自由文本矩阵（2026-09-17 测）

10 格全数（coding/json/prose × C1/2/4/8/16）见 `data/` 原始归档；关键格：

| 格 | decode tps | agg |
|---|---|---|
| coding-C1 | 62.3 | 62.3 |
| coding-C8 | — | 222.6 |
| coding-C16 | — | 356.1 |
| prose-C16 | — | 358.6 |

## §3 DE 结构化矩阵（2026-09-18 补录，xgrammar json_schema 约束）

| task | C | prefill | decode | agg | median ct |
|------|---|---------|--------|-----|-----------|
| coding | 1 | 551.2 | 89.5 | 89.5 | 4096 |
| coding | 2 | 424.4 | 57.9 | 115.9 | 4096 |
| coding | 4 | 258.1 | 45.6 | 182.6 | 4096 |
| coding | 8 | 172.0 | 26.3 | 210.4 | 4096 |
| coding | 16 | 70.5 | 23.0 | 367.2 | 4096 |
| json | 1 | 470.0 | 30.2 | 30.2 | 4096 |
| json | 2 | 425.4 | 33.3 | 66.5 | 2278.5* |
| json | 4 | 338.6 | 31.6 | 126.2 | 4096 |
| json | 8 | 240.8 | 22.9 | 183.5 | 1751.0* |
| json | 16 | 118.6 | 16.9 | 269.8 | 4096 |

\* 少数 wave schema 提前满足自然收束（语义内行为，decode 已按 (ct−1)/(wall−ttft) 归一）。

**结构化 vs 自由文本**：coding C1 +43.7%（token 形态效应，非引擎增速）；C8 −5.5% / C16 +3.1%（收敛）。
**json agg 随并发增长弱于 coding**（C16 = 8.9× C1 vs coding 4.1×）——grammar batch 开销高并发显著。

### 结构化通道两个坑（工程记录）

1. 🔴 `sampling_params.json_schema` 传 **dict** 会崩引擎（xgrammar `TypeError: unhashable type: 'dict'`
   → scheduler 死 → 容器 247）。**必须传 JSON 字符串**。
2. 🟠 grammar 约束下 `ignore_eos=True` 失效：schema 可终止时 EOS 照常 stop。
   要吃满预算，schema 必须带 `minItems` 等不可提前满足的约束。

## §4 PR 矩阵（2026-09-17 测）

30 格全数见 `data/` 归档；峰值格：PR32768-C1 3,352 / 总 PR PR32768-C16 6,319。

## §5 质量门

- GSM8K 200 题（600K 在役，fp4idx 关）：0.9600
- GSM8K（fp4idx 开，干净样本 i0–107）：107/108（基线同期 106/108，无回退）

## §6 fp4-indexer A/B（2026-09-17）

code-256 同口径：c1 −6.4% / c8 −0.9% / c16 −3.3%（轻微负向，保留观察；质量门 PASS）。

## §7 RoCEnante one-shot RDMA（2026-09-17/18）——**否决归档**

b12x `comm/roce` + SG17 patch + TP4 adapt 全部接线成功，但 QP 建联超时（RTR timeout）。
根因：**物理布线与 one-shot 全互联不兼容**——GID3 表显示四机 HCA 分属两个互不互通的网段
（186/188 = 10.100.140/141.x；187/189 = 10.20.0.x 点对点），one-shot RDMA 要求 rank 两两直连，
环型 P2P 布线只保证邻居互通。NCCL RING 不受影响（复用同环）。处置：env/overlay 全部回滚，
生产回 NCCL RING 路径。补丁与部署脚本留档 `/tmp/rocenante-deploy/`（临时，不入库）。

## §8 网关链路（8001）性能注记（2026-09-18）

8001（concurrency-proxy-v2）与直连 8899 对比：
- **流式**：8001 wall 48.68s vs 8899 57.74s（**−15.7%，网关反而更快**；heartbeat 与 chunked 泵送效应）
- **非流式**：8001 140.45s vs 8899 54.77s（**+156.4%**）——非流式大响应在网关侧整包缓冲
  （`relay_plain` 的 `await up.read()`）且与 queue/semaphore 交互，大 payload 显著劣化。
- 结论：**PR/长输出压测一律走流式**；非流式大响应不建议经 8001。

## §9 环境指纹

- driver 580.173.02 / CUDA 13.0 · NCCL 2.30.7 ring-only · 镜像 `dsv41-sglang-optimized:v7`
- 时区 UTC · B1 固化参数继承 · 治理钉 pool≥16×ctx fail-closed

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
