# AUTOTUNE GOLDEN 锁定与重建规程

> 首版 2026-09-21（部署侧规程）· 2026-09-24 脱敏发布并校准口径。
> 本仓相关面：`scripts/gate.sh`（「autotune golden 锁定」检查项）、`start.sh`
> （`AUTOTUNE_GOLDEN_DATA` 的 bind-mount）、
> [`sglang-overlay/README.md`](../../sglang-overlay/README.md)（**镜像内**运行时代码的权威清单）、
> [`BUILD-IDENTITY.md`](../../BUILD-IDENTITY.md)（镜像身份与构建锚）。

## 先读这一节：占位符，以及「不随本仓分发」的对象

- `<head-node>` / `<worker-rank1>` / `<worker-rank2>` / `<worker-rank3>` 指代你自己的四台机器
  （1 台 head + 3 台 worker）的 SSH 别名。照抄命令前请替换。
- 文中出现的 `~/w6-kit/…`、`~/v41-028-build-…/`、`~/r4-ops-work/…`、`autotune-golden/` 都是
  **部署宿主上的运维对象，不随本仓分发**。保留这些路径是为了留下数字的来路（provenance），
  不是让读者去打开它们。
- **可以自己核对的**：`sglang-overlay/README.md` 的镜像侧文件清单 ·
  [`RELEASE-NOTES-v0.2.8.md §2`](../release-notes/RELEASE-NOTES-v0.2.8.md) 的逐件判词 ·
  [`scripts/verify_release_artifact.py`](../../scripts/verify_release_artifact.py) 对发布 tar 的离线复算 ·
  [`docs/CONFIG-v0.2.8-ENV.md`](../CONFIG-v0.2.8-ENV.md) 的逐键对照表。

## 背景

FlashInfer autotune 战术表曾是「09-19 v13 抽签烘进镜像 + 每靴 1/4 票决覆写」的偶然锁定
（部署侧的 `guard/BASELINE.md` 自证「钉住表不保证每区间最优」；判据：投票策略性能差、无质量判别）。
本规程把锁定变成设计行为，并给重建加质量门。

## 在役机制（零操作，自动）

- `start.sh` 把 `~/dsv41-flash-dgxsparks/autotune-golden/data/` bind-mount（RW）到容器
  `/root/.cache/sglang/flashinfer/autotune`；四机 rsync 对齐同树。
- 四 rank 各自命中预置的同表 rank 文件 ⇒ `_drop_diverged_autotune_cache` 的 digest all-gather 全等
  ⇒ 表决 no-op ⇒ 跨靴跨机确定，无冷签彩票。
- `scripts/gate.sh` 的「autotune golden 锁定」检查项：挂载在场 + 宿主树与 MANIFEST 逐文件 md5 一致
  + 无 manifest 外新键。冷签落地 = gate FAIL 拦截，逼走本规程。

## 缓存键何时变（= 何时会冷签）

`flashinfer_autotune_cache_path()` 的键 = 模型路径 / dtype / quant / moe backend / tp=4 / ep=2 /
skip_ops 等哈希。**改 chunk 不会变键**（不在键里；`schedule_policy` 也不在键内 —— 09-21 SPF 靴
golden 命中实证）；换量化 / backend / tp 拓扑会变 ⇒ 新键目录无预置文件 ⇒ 四 rank 全空 ⇒ 冷签
（日志 `tuning from scratch`）⇒ 冷签结果写进宿主 golden 树（RW 挂载）⇒ gate 拦截。

**⚠ 审计补记（两成分曾漏记）**：缓存**路径**还含 `<flashinfer_version>/<arch>` 两级目录
（现役 `0.6.18/sm121/`）——**FI 版本升级（0.6.18 → 0.7.x）或 arch 变化 = 整树新目录 = 全量新键
= 四机全量冷签彩票**，且旧表跨版本不可移植（`load_configs` 的 metadata 六字段硬校验会拒载手工搬来的
旧目录）。**升级镜像前必须先走本规程。**
另：digest 含 flashinfer / cuda / cublas / cudnn 版本串 —— **单机驱动或库的局部升级会使该 rank 的
digest 独异 ⇒ 每靴重签 + golden 文件被反复覆写**；任何一台升级驱动前先四机比对 metadata
（比对法见下「sync-golden」）。

## 重建规程（质量门 —— 冷签表未过门不得晋升）

1. **触发**：gate 报「manifest 外新键」，或主动想重抽战术表。
2. **隔离**：把宿主树里的新键目录移出 golden：
   `mkdir -p ~/dsv41-flash-dgxsparks/autotune-golden/staging && mv ~/dsv41-flash-dgxsparks/autotune-golden/data/<ver>/<arch>/<newkey> ~/dsv41-flash-dgxsparks/autotune-golden/staging/`
   ⚠ **四台都做**（冷签是四机各写各的本地树 —— 只把 head 移出，worker 上的半成品旧冷签仍会在下靴
   以 3/4 票被表决采纳、回灌 head 干净树；真多数门槛同样拦不住 3 票块）。
   ⚠ **勿用 `AUTOTUNE_GOLDEN_DATA=staging` 起栈的老方案**：worker 侧旧版曾硬编码挂在役树
   （09-21 审计 P1；现行 `start.sh` 已改 head/worker 同源变量，但跨机一致性仍以 `mv` 物理隔离为最稳）。
3. **冷签**：起栈（此时四机均无该键缓存），日志确认 `tuning from scratch` 字样 + 表决采纳。
4. **质量门（判别这张签配不配当 golden）**：
   - warmup t/s ≥ **650**（v13 健康参考 745）；
   - PRv3 8192-c1 ≥ **4500 t/s**（V4B 健康锚 4992）；
   - （可选加强）131072-c1 ≥ 4000。
   ⚠ 前提 = 四机时钟健康（负载态 2380+ MHz；2026-09-21 教训：某机楔死 721 MHz 时任何采分全部作废）。
5. **不过门**：`./stop.sh` → **四台**清 staging 新键 → 重新起栈重抽（**上限 3 次**；连挂 3 次停手转人工
   —— 可能是环境病不是签不好）。
6. **过门**：把 staging 的四份 rank 文件收入 `data/<ver>/<arch>/<key>/`，更新 `MANIFEST.json`
   （`file_md5` + `quality` 字段填实测值），四机对齐（`./start.sh sync` 是拒绝 rsync 476 GiB 的桩，
   **勿走**；用下面「sync-golden」的精确命令）→ 起栈 → gate 三项全绿 → 完成。
   收尾必跑 `bash ~/w6-kit/powercycle_check.sh` 的 golden 段确认四机全树一致。

## sync-golden（四机对齐唯一正确姿势）

```bash
cd ~/dsv41-flash-dgxsparks
# 把 head 的 golden 树推给三个 worker（替换成你自己的 SSH 别名）
for h in <worker-rank1> <worker-rank2> <worker-rank3>; do
  rsync -a --delete autotune-golden/ "$h:dsv41-flash-dgxsparks/autotune-golden/"
done

# 聚合校验（⚠ sort 必须钉 LC_ALL=C；且前缀写法只作用于管道首命令 —— 直接前置 sort）：
for h in <head-node> <worker-rank1> <worker-rank2> <worker-rank3>; do
  ssh "$h" 'find "$HOME/dsv41-flash-dgxsparks/autotune-golden" -type f -name "*.json" | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-12'
done   # 四值必须全等（绝对路径口径；2026-09-21 锚 = 7f9cc0ad）
```

`--delete` 是有意的：这套命令的语义是「以 head 为准的镜像」，不是合并。**先确认 head 树是过门后的
形态**，再推。

## 表决语义：rank 分歧时怎么办

镜像内 `.../model_executor/runner/flashinfer_autotune.py` 存在两个世代，**分歧发生时行为不同**：

| 世代 | md5 | 采纳语义 | 落在哪 |
|---|---|---|---|
| 单票（旧） | `dc56549b6331d0c72e46af19680e8480` | 只对**非空** digest 计数（`counts[d]` 仅在 `if d:` 时累加），**1 票即采纳**，并覆写 minority rank 的 golden 文件 | `0.2.7` 及更早 |
| 真多数（v14） | `e6f4d696f70d7426aeb2fb9a653e23ba` | `len(digests) // 2 + 1` 门槛（4 rank 需 3 票，不足 = 按冷签处理）+ 全等态日志 + `SGLANG_FI_GOLDEN_DIGEST` 断言钩子 | **`0.2.8pre` 起，含 `0.2.8` 生产** |

**现状（2026-09-24）**：生产 pin = `dsv41-sglang-optimized:0.2.8`（内容身份 `4cca364c46778423`，
3 层），其 COPY 层内含 v14 ⇒ **生产已受真多数门槛保护**，`0.2.7` 的单票语义退为历史。

> **⚠ 判据的取法（这一条最容易被搞错）**：**不要用本仓 `sglang-overlay/` 里的同名文件推镜像语义。**
> 那个目录是**开发模式的宿主覆盖位**，且其自述「尚未与任何已发布镜像逐字节对齐」—— 其中
> `flashinfer_autotune.py` 恰恰是旧世代（`dc56549b`）。要看镜像里跑的是哪一版，用镜像侧的证据：
>
> - 权威清单 —— [`sglang-overlay/README.md`](../../sglang-overlay/README.md) 的
>   「0.2.8 镜像内的运行时代码」表（11 件，本文件一项 = `e6f4d696f70d7426aeb2fb9a653e23ba`）；
> - 逐件判词 —— [`RELEASE-NOTES-v0.2.8.md §2`](../release-notes/RELEASE-NOTES-v0.2.8.md)；
> - 离线自证 —— 发布 tar 的 COPY 层可整层抽出并逐件比 md5（命令见 `sglang-overlay/README.md`）。

**golden 锁在役时两版行为一致**（digest 全等 ⇒ no-op）；分叉只在「不一致发生时」显形：
单票版会采纳 1 票块，v14 弃之、按冷签处理。

**MANIFEST 自证缺口（登记，未改）**：`~/dsv41-flash-dgxsparks/autotune-golden/MANIFEST.json` 确实存在，
且确实有 `lock_semantics` 字段，但该字段下只有 `mount` / `why_rw` / `gate` / `rebuild` 四个键，
**没有任何表决语义子字段**。⇒ 表决语义只活在镜像内的那个源文件里，台账不自证。
若要让台账自证，需给 `lock_semantics` 加一个显式子键（如 `vote_rule`）；本次**未加**，
登记为待办，不假装已落地。

## 两条旧告诫的处置（2026-09-23）

1. ~~「下次镜像重建会**静默**把 v14 烘进生产」~~ ⇒ **已在 `0.2.8pre` 构建中显式确认晋升**：
   构建脚本的载荷表带注释点名该文件。重建「顺手带上」已是现状而非意外。
   **但改这个文件仍要在重建 checklist 上点名** —— 它管的是每靴冷签的采纳语义，改动影响的是
   「分歧时怎么办」这条底线，不能靠 diff 大小判断。
2. ~~「并同步更新 `MANIFEST.lock_semantics`」~~ ⇒ 取证结论见上：该字段下没有表决语义子键，
   所以这一半**无需改动即可结清，结清方式是「确认无事可做」，不是「改过了」**。
   根因：表决语义从来只活在镜像内的 `flashinfer_autotune.py` 里；`MANIFEST.json` 只描述挂载方式与
   gate 判据。

## 已知限制

- 钉住表是「某一次的签」：对当前业务负载（chat prefill 4–131K 档）验证过即可，不追求全区间最优
  （与部署侧判例一致；470K+ 档留给业务验证）。
- 主/草稿两键当前同表（md5 一致）是实测形态，非必然；重建后允许异表。
- RW 挂载是**有意的**（RO 会让冷签路径 unlink/write 抛 `OSError` 崩靴）；「写进宿主」由 gate 拦截
  兜底，不是漏洞。
- gate 的 golden 三层断言只看 **head** 侧；worker 树漂移靠 `powercycle_check.sh` 的四机全树对比兜底
  （起栈前 `start.sh` 也会断言 worker 树在场，09-21 补）。
- `SGLANG_FLASHINFER_AUTOTUNE_CACHE=0` 模式会在 golden 树内写 `runs/` 时间戳文件 —— gate 的漂移检查
  可能将其报为「无此条目」（方向保守，但属误报源）；勿在生产开该模式，或在 `find` 中排除 `*/runs/*`。
