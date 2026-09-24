# 提交历史重写说明 / Commit-history rewrite, 2026-09-24

## 一句话 / In one line

2026-09-24 本仓库的**提交历史被重写**：每个提交的**内容不变**，但**哈希全部改变**
（2026-09-18 及其后的提交）。三个 tag 已在同一次操作中更新。

On 2026-09-24 this repository's **commit history was rewritten**. Every commit's
**content is unchanged**; the **hashes are not** — all commits from 2026-09-18
onward. The three tags were updated in the same operation.

## 为什么 / Why

一次凭据卫生修复需要把敏感值从历史中移除。删除文件只能止住当前的暴露，**无法撤销
已经发生的暴露**——轮换凭据才是解除风险的根本手段，编辑或重写历史都只是止血。

A credential-hygiene fix required removing sensitive values from history.
Deleting a file stops the bleeding; it does not undo an exposure that already
happened. **Rotating the credential is the remedy** — editing or rewriting
history is only first aid.

## 你需要做什么 / What to do

| 你的情况 / Your situation | 动作 / Action |
|---|---|
| 持有旧的 clone | 重新 clone，或 `git fetch --all && git reset --hard origin/main` |
| 持有 fork | 同步或删除——你的 fork 保留了重写前的历史 |
| 文档、脚本里引用了提交哈希 | 本仓库内的引用**已全部同步**到新值（22 处 / 5 个文件） |
| 依赖 `refs/pull/*` 或旧 tag 的对象 | 这些引用不在本次重写的作用范围内 |

## 内容未变，可自行核对 / The content did not change — verify it yourself

重写是**只动历史、不动现状**的操作。操作前后 `main` 的顶层树对象逐字节相同：

The rewrite touched history only. The top-level tree of `main` is byte-identical
before and after:

```
fe2c028d885da3d20ffcb8ffc3914489ee0ff0c0
```

即 `git rev-parse 'HEAD^{tree}'` 在重写前后打印同一个值（此后正常的新提交会让它前进）。

## 当前锚点 / Current anchors

| 引用 / Ref | 值 / Value |
|---|---|
| `v0.2.3` | `0663769fe98d74c17026cebf2999e8b7f8d48618` |
| `v0.2.4` | `1c44900629ca61de9e4ff1b4ff2e7b7a92538227` |
| `v0.2.4-baseline-v18` | `5543e169b5e258b7dd536494ea8610287a26f26be` |

以上三个 tag 在本次重写中一并更新；它们指向的**内容**与重写前相同，只有哈希不同。

## 这把尺子 / How the rewrite was gated

重写不是「看起来没问题」就放行。放行前通过了四项机械判据：

1. **凭据扫描归零**：对**全部对象**（含不可达）做形状级扫描，重写前 4 处命中 → 重写后 0 处；
2. **现状逐字节不变**：791 条目录项逐条比对，0 处差异；
3. **差异收窄**：三个 tag 各自只有 1 个文件与重写前不同，即被替换的那一个；
4. **远端独立验收**：从 GitHub 重新 clone 一份，对副本再跑同一把尺子，0 处命中。
