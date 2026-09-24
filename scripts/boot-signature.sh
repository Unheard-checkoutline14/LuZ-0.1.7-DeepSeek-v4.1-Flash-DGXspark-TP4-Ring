#!/usr/bin/env bash
# boot-signature.sh — 起栈签名检查（靴态），补上质量门查不出的那一维。
#
# 由来：2026-09-16 慢靴事故 —— 质量门（gate 4/4、code 12/12、corruption 0 U+FFFD）**全绿**，
# 但生产解码慢 ~10-25×（c1 2.4 t/s vs 56.8；decode 1.75 s/步 vs ~0.06）。
# 快慢两靴**配置逐字节相同**（`.env.tp4` md5 相同），唯一变量是"哪一次靴"。
# 处置 = 配置不动直接重启（2026-09-16 实测单次重启即恢复）。
#
# ★★ 判据在 2026-09-16 晚**被实测推翻过一次**，本版是修订版（依据 `SLOWBOOT-FORENSICS.md`）：
#   · 旧版主判据是 `capture elapsed > 20s`。**已证伪（既不充分）**：
#       2026-09-14 04:14 靴 capture=**30.00s**（2.90s/层，与慢靴同族）却**健康**
#       （warmup 12s、探针 57-67 t/s）⇒ 单靠 capture 会把好靴重启掉。
#   · `Warm-up done in Ns` **从判据中删除**：健康靴也有 141s/250s 的，
#       那是 **prompt 工作量驱动**（257K/474K token），不是靴态。
#   · 新主判据 = **warmup 块的 per-batch `input throughput (token/s)` 中位数**：
#       同一份日志自带、**零流量依赖**、且分离度大：
#         健康 13:10 靴 **median 663**（n=8）  vs  慢靴 09:55 靴 **median 55**（n=17）
#         （独立复算：本文件作者用暖靴/慢靴两段切片实算，非转述）
#   · capture elapsed 保留为**警告**：它不能单独触发重启，但值得记一笔。
#
# 用法：
#   boot-signature.sh            # 只读日志判靴态（零成本、零流量）
#   boot-signature.sh --bench    # 追加 canonical 吞吐（会起流量，~400s）
#
# ⚠GB10 环境已知不可读字段（别在这上面浪费时间）：`clocks.memory` / `supported_clocks`
#   / `power.limit` 均为 **N/A**；DCGM 在 GB10 无 DRAM 计数器。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 2026-09-21 白盒修正：旧默认 logs-tp4/dsv41.log 是陈旧目录（现役=logs/dsv41.log），
# 靴态判定读错文件；DSV41_LOG 显式指定仍优先
LOG="${DSV41_LOG:-$ROOT/logs/dsv41.log}"
[ -f "$LOG" ] || LOG="$ROOT/logs-tp4/dsv41.log"
KEY="${DSV41_API_KEY:-$(grep -m1 '^API_KEY=' "$ROOT/.env.tp4" 2>/dev/null | cut -d= -f2-)}"
DO_BENCH=0
[ "${1:-}" = "--bench" ] && DO_BENCH=1

fail=0
say() { printf '%s %s\n' "$1" "$2"; }

# ---- 1) ★主判据：warmup 块的 per-batch 吞吐中位数 ---------------------------
# warmup 块 = `The server is fired up and ready to roll!` 之后、`Warm-up done in ...` 之前。
# 这一段**每次起栈必有**，所以本判据在全新靴上也能判定（这是它优于 decode 间隔的地方，
# 后者要等流量才有采样，见下方 3)。
warm="$(python3 - "$LOG" <<'EOF' 2>/dev/null
import re, statistics as st, sys
lines = open(sys.argv[1], errors='ignore').read().split('\n')
lo = hi = None
for i, l in enumerate(lines):
    if lo is None and 'The server is fired up and ready to roll' in l:
        lo = i
    if lo is not None and 'Warm-up done in' in l:
        hi = i
        break
if lo is None or hi is None:
    print(""); raise SystemExit
vals = []
for l in lines[lo:hi]:
    m = re.search(r'input throughput \(token/s\): ([0-9.]+)', l)
    if m:
        vals.append(float(m.group(1)))
if not vals:
    print(""); raise SystemExit
dur = re.search(r'Warm-up done in (\d+)s', lines[hi])
print(f"{st.median(vals):.1f} {min(vals):.1f} {max(vals):.1f} {len(vals)} {dur.group(1) if dur else '?'}")
EOF
)"
if [ -n "$warm" ]; then
  wmed="$(echo "$warm" | awk '{print $1}')"; wmin="$(echo "$warm" | awk '{print $2}')"
  wmax="$(echo "$warm" | awk '{print $3}')"; wn="$(echo "$warm" | awk '{print $4}')"
  wdur="$(echo "$warm" | awk '{print $5}')"
  if awk "BEGIN{exit !($wmed < 200)}"; then
    say '[✗]' "warmup 吞吐中位=${wmed} t/s (<200；健康 388-709，慢靴 ~55；n=${wn}, min=${wmin}, max=${wmax}, warmup ${wdur}s)"
    say '[✗]' "⇒ **判慢靴态** ⇒ 处置=**配置不动重启**（实测单次重启即恢复）"
    fail=1
  elif awk "BEGIN{exit !($wmed < 400)}"; then
    say '[!]' "warmup 吞吐中位=${wmed} t/s 在 200-400 灰区（n=${wn}, warmup ${wdur}s）⇒ 建议 --bench 复核"
  else
    say '[+]' "warmup 吞吐中位=${wmed} t/s（n=${wn}, min=${wmin}, warmup ${wdur}s）⇒ 靴态正常"
  fi
else
  say '[!]' "找不到 warmup 块（日志里没有 'fired up'/'Warm-up done' 对）—— **主判据未判定**；若刚起栈请稍后重跑"
  fail=1
fi

# ---- 2) 参考项：capture elapsed（**降级为警告，不能单独触发重启**）---------
cap="$(sed -n 's/.*Capture target verify CUDA graph end\. elapsed=\([0-9][0-9.]*\) s.*/\1/p' "$LOG" 2>/dev/null | tail -1)"
if [ -z "$cap" ]; then
  say '[i]' "读不到 capture elapsed（日志缺该行）—— 参考项跳过"
elif awk "BEGIN{exit !($cap > 10)}"; then
  say '[!]' "capture=${cap}s > 10s（健康 5.7-6.7s）—— ⚠**仅供参考**：2026-09-14 有 capture=30.0s 而健康的反例 ⇒ 本项**不单独判 FAIL**；以 warmup 吞吐为准"
else
  say '[+]' "capture=${cap}s（参考项，正常）"
fi

# ---- 3) decode 40 步间隔：需流量；有流量时是强判据 -------------------------
cad="$(python3 - "$LOG" <<'EOF' 2>/dev/null
import re,sys
from datetime import datetime
ts=[m.group(1) for m in (re.search(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[^\]]*\] Decode batch',l) for l in open(sys.argv[1],errors='ignore')) if m]
# 只取最近 12 个间隔：解码行每 40 步打一行，但**空闲期不打** ⇒ 大间隔既可能是慢靴、
# 也可能是"引擎空转"，中位数会把空转误判成慢靴（2026-09-16 实测踩到：空闲 2h ⇒ 中位 1244s）。
# 判"慢"要用**最快的一档**：min = 最近实际跑出的最好 40 步耗时。空闲间隔只会更大，永不误伤。
if len(ts)<4: print(""); raise SystemExit
d=[(datetime.strptime(ts[i],'%Y-%m-%d %H:%M:%S')-datetime.strptime(ts[i-1],'%Y-%m-%d %H:%M:%S')).total_seconds() for i in range(1,len(ts))]
d=d[-12:]
print(f"{min(d):.1f} {sorted(d)[len(d)//2]:.1f} {len(d)}")
EOF
)"
if [ -n "$cad" ]; then
  cmin="$(echo "$cad" | awk '{print $1}')"; cmed="$(echo "$cad" | awk '{print $2}')"; cn="$(echo "$cad" | awk '{print $3}')"
  if awk "BEGIN{exit !($cmin > 20)}"; then
    say '[✗]' "decode 40 步**最快**间隔=${cmin}s（正常 2-6s；中位 ${cmed}s，n=${cn}）⇒ **每步开销异常**（慢靴 ~70s）"
    fail=1
  else
    say '[+]' "decode 40 步最快间隔=${cmin}s（中位 ${cmed}s，n=${cn}）⇒ 步时正常"
    awk "BEGIN{exit !($cmed > 20)}" && \
      say '[i]' "中位 ${cmed}s 偏大但最快仅 ${cmin}s ⇒ 判**空闲/低流量**，非慢靴（避免误报）"
  fi
else
  say '[i]' "decode 采样不足（<4 行）—— 步时维**未判定**（本项需流量；主判据不依赖它）"
fi

# ---- 4) 可选：canonical 吞吐 ----------------------------------------------
if [ "$DO_BENCH" = "1" ]; then
  if [ -z "$KEY" ]; then say '[!]' "拿不到 API key，跳过 bench"; else
    out="$(timeout 400 python3 "$ROOT/bench/bench_tp.py" --base http://127.0.0.1:8899/v1 \
             --model deepseek-v4.1-flash --key "$KEY" --conc 1 --max-tokens 400 \
             --prompt-type code 2>&1 | tail -3)"
    echo "$out"
    tps="$(echo "$out" | awk '/^ *1 /{print $4}')"
    ttft="$(echo "$out" | awk '/^ *1 /{print $2}')"
    if [ -z "$tps" ]; then
      # 审计 P1 修：解析空（bench 超时被杀/输出格式漂移）恰是 --bench 要抓的挂死
      # 形态——旧逻辑 `[ -n ]` 短路后走 else 假绿「吞吐正常」。
      say '[✗]' "bench 无有效输出（超时/格式漂移——raw: $(echo "$out" | tr '\n' ' ' | cut -c1-120)）⇒ 按不可信判"; fail=1
    elif awk "BEGIN{exit !($tps < 20)}"; then
      say '[✗]' "bench c1=${tps} t/s (TTFT ${ttft}) < 20 ⇒ **判慢靴，重启**（配置不动）"; fail=1
    else
      say '[+]' "bench c1=${tps} t/s (TTFT ${ttft}) ⇒ 吞吐正常"
    fi
  fi
fi

echo
  # DSV41 2026-09-19：无抽签断言（慢靴根因=autotune tactic 彩票）
  _DL=$(docker logs dsv41-head 2>&1 || true)
  if [ "$fail" = 0 ] && grep -q "tuning from scratch" <<<"$_DL"; then
    echo "[!] 检测到 autotune 冷启动重签 —— 本靴 tactic 为新抽，慢靴风险；重启一次再判"
    exit 1
  fi
  if [ "$fail" = 0 ] && grep -q "majority-vote adopted" <<<"$_DL"; then
    echo "[+] autotune tactic 已钉住（多数表决采纳，无重抽）"
  fi
  # 2026-09-21 门禁统筹④：warmup 墙钟地板（R9 慢签 warmup 663s vs 健康 44-66s）
  # + autotune golden 在役正断言（golden 锁下四 rank 同表⇒无表决行，旧的
  # majority-vote 正断言不再出现属预期；改查挂载）。慢 warmup 的两大史因=
  # tactic 慢签（autotune）与 02 型时钟楔死（PD 安全模式，runbook §7）。
  _wu=$(grep -oE 'Warm-up done in [0-9]+s' <<<"$_DL" | grep -oE '[0-9]+' | tail -1)
  if [ -z "$_wu" ]; then
    # 审计 P2 修：docker logs 不可读（|| true 吞错）或格式漂移时本检查一行不出——
    # 既不 FAIL 也不留痕。无法判定=FAIL。
    say '[✗]' "warmup 墙钟地板无法判定（docker logs 不可读/无 Warm-up done 行——新镜像改了日志格式？）"; fail=1
  elif [ "$_wu" -gt 300 ]; then
      say '[✗]' "warmup=${_wu}s >300s 地板 —— 慢靴。分诊：①docker logs 查 majority-vote/tuning-from-scratch（autotune 签）②~/w6-kit/guard/guardctl.sh doctor 的 GPU burn 探针（PD 时钟楔死：修复=拔墙上 AC 冷断电）"
      fail=1
    else
      say '[+]' "warmup=${_wu}s ≤300s（健康带 44-66s；R9 慢签 663s）"
    fi
  if docker inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' dsv41-head 2>/dev/null | grep -q 'autotune-golden/data'; then
    echo "[+] autotune golden 在役（宿主钉住表挂载，表决 no-op 属预期）"
  else
    # 审计 P2 修：正断言 only——未挂载时一行不出=锁定被绕过而无人知（与 gate 的
    # 强断言分工：此处留痕即可，FAIL 由 gate 判）
    echo "[!] autotune golden 未挂载（锁定被绕过——gate 将判 FAIL；确认非有意停用）"
  fi
  if [ "$fail" = 0 ]; then echo "[+] BOOT SIGNATURE OK"; else
      echo '[✗] BOOT SIGNATURE FAIL —— 质量门查不出这个；处置见本脚本头部注释'
  fi
  exit "$fail"
