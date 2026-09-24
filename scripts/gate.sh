#!/bin/bash
# gate.sh — 「容器 Up ≠ 服务可信」。一次判定当前引擎是否可交付。
#
# 用法：
#   gate.sh            快档（~2 分钟）：/health + 算术 + 结构化 + 工具 + corruption + code-gate
#   gate.sh --full     全档（~12 分钟）：快档 + 终止性 + needle 梯度(30K/229K/470K)
#   gate.sh --json     机器可读汇总（最后一行 JSON）
#
# 退出码：0 全过 · 1 有失败
#
# 设计取舍：默认快档要能在一次换班/切换后立刻跑完，覆盖「最常被打断的正确性」
# 而非吞吐；吞吐由 bench/ 下的基准负责。

set -uo pipefail

# overlay md5 断言块要读仓库根的 start.sh 抽 SGLANG_OVERLAY_MAP；start.sh 不 export
# ROOT，缺省定义必须在此处补齐，否则 set -u 下进程替换子壳静默死、循环 0 迭代
# （恒假 PASS——QA 验收 F-1 教训）。
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

PORT="${SERVER_PORT:-8899}"
KEY_FILE="${API_KEY_FILE:-$HOME/dsv41-flash-dgxsparks/state-tp4/api-key}"
BASE="http://127.0.0.1:${PORT}"

# ── 主机清单：与 IB_HCA 同款纪律（2026-09-20 F3）——来自部署配置面，不硬编码 ──
# .env.tp4 的 WORKER_HOSTS / WORKER_IPS 书写顺序 = rank 顺序（第 1 个是 rank1）。
# 缺省值是**占位符**：读者须换成自己集群的 SSH 别名，不是可运行值。
_ENVF="${DSV41_ENV_FILE:-$HOME/dsv41-flash-dgxsparks/.env.tp4}"
_env1() { grep -m1 -E "^$1=" "$_ENVF" 2>/dev/null | cut -d= -f2- | tr -d '"'; }
_WORKERS="${WORKER_HOSTS:-$(_env1 WORKER_HOSTS)}"
_WORKERS="${_WORKERS:-<worker-rank1> <worker-rank2> <worker-rank3>}"
_HEAD_H="${HEAD_HOST:-$(_env1 HEAD_HOST)}"
_HEAD_H="${_HEAD_H:-$(hostname -s)}"
FULL=0
JSON=0
for a in "$@"; do
  case "$a" in
    --full) FULL=1 ;;
    --json) JSON=1 ;;
  esac
done

KEY=""
[[ -f "$KEY_FILE" ]] && KEY="$(cat "$KEY_FILE")"
auth=()
[[ -n "$KEY" ]] && auth=(-H "Authorization: Bearer $KEY")

pass=0; fail=0
declare -a results=()
ok()   { results+=("PASS  $1"); pass=$((pass+1)); echo "[+] $1"; }
bad()  { results+=("FAIL  $1"); fail=$((fail+1)); echo "[x] $1"; }

ask() {  # ask <json-body>
  curl -s --max-time 300 "${auth[@]}" -H 'Content-Type: application/json' \
    -d "$1" "$BASE/v1/chat/completions"
}

# ── 1. 健康 ────────────────────────────────────────────────────────────────
# DSV41 2026-09-19 P2⑤：IB 口状态零流量断言（客户坑 1 前置）
# 2026-09-20 F3：设备清单动态化（.env.tp4 IB_HCA 优先 → /sys/class/infiniband 实测
# 回退），不再硬编码口名——口名漂移时旧断言会静默漏测；ok 行改按实测计数打印
# （旧版循环后无条件 ok，坏口会同时产生一条 FAIL 和一条「四口全 ACTIVE」假 PASS）。
_IB_LIST="${IB_HCA:-$(grep -m1 -E '^IB_HCA=' "$HOME/dsv41-flash-dgxsparks/.env.tp4" 2>/dev/null | cut -d= -f2)}"
_IB_LIST="${_IB_LIST:-$(ls /sys/class/infiniband 2>/dev/null | paste -sd, -)}"
if [ -z "$_IB_LIST" ]; then
  bad "无 IB 设备可断言（/sys/class/infiniband 为空且 .env.tp4 未设 IB_HCA）"
else
  _ib_ok=0
  for _ibd in ${_IB_LIST//,/ }; do
    _st=$(awk '{print $2}' /sys/class/infiniband/$_ibd/ports/1/state 2>/dev/null)
    if [ "$_st" = "ACTIVE" ]; then
      _ib_ok=$((_ib_ok + 1))
    else
      bad "IB 口 $_ibd state=${_st:-无此设备}（应 ACTIVE）—— 环网物理层故障前置"
    fi
  done
  [ "$_ib_ok" -gt 0 ] && ok "IB 口 ACTIVE $_ib_ok 个（清单：$_IB_LIST）"
fi
# DSV41 2026-09-19 P2⑥：内核守卫（客户坑 2：7.0.0-1019 打瘫 NCCL 的故障内核）
KERN=$(uname -r)
if [[ "$KERN" == 7.0.* ]]; then
  bad "内核 $KERN = 已知打瘫 NCCL/RoCE 的故障内核（ibv_reg_mr_iova2 ENOMEM）；须回退 6.17.0-1031+"
fi
# 2026-09-20 F5：NV_ERR_NO_MEMORY 计数（kernel log；dmesg 普通用户被拒，走
# journalctl -k）。首跑即抓到 01 机本靴 379 条：三簇历史（09-18 17:00 chunk 两靴 /
# 09-19 01-04h 疑似夜间 bench 容器 / 09-20 07:33-09:41 维护窗 OOM 事件）+ 当前生产
# 3h+ 零新增 ⇒ 判定语义 = **head 容器本次启动以来**有新增才 FAIL（本栈生命周期内
# 的驱动 OOM 才是本次部署的问题）；历史簇随上下文行展示，重启才清、不可永久打红。
_gate_since=$(docker inspect -f '{{.State.StartedAt}}' "${HEAD_CTN:-dsv41-head}" 2>/dev/null | sed 's/\..*Z/Z/')
[ -z "$_gate_since" ] && _gate_since='-6h'
# 2026-09-20 H9：journalctl 不可读时报 n/a 而非假 0（读不到 ≠ 零事件）
if journalctl -k --since "$_gate_since" --no-pager >/dev/null 2>&1; then
  # 启动窗（StartedAt+12min）内的 NV_ERR = 图捕获/内存峰值的分配重试瞬态（0.2.6 实测
  # 5 条全在 +6min 且稳态零新增，与历史三簇同指纹）；稳态期新增才是真故障。
  _boot_end=$(date -u -d "$_gate_since + 12 minutes" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)
  if [ -n "$_boot_end" ]; then
    _nverr_boot=$(journalctl -k --since "$_gate_since" --until "$_boot_end" --no-pager 2>/dev/null | grep -c 'NV_ERR_NO_MEMORY')
    _nverr_new=$(journalctl -k --since "$_boot_end" --no-pager 2>/dev/null | grep -c 'NV_ERR_NO_MEMORY')
  else
    _nverr_boot=0
    _nverr_new=$(journalctl -k --since "$_gate_since" --no-pager 2>/dev/null | grep -c 'NV_ERR_NO_MEMORY')
  fi
  _nverr_all=$(journalctl -k --no-pager 2>/dev/null | grep -c 'NV_ERR_NO_MEMORY')
  if [ "${_nverr_new:-0}" -gt 0 ]; then
    bad "kernel log NV_ERR_NO_MEMORY 稳态期 ×${_nverr_new}（启动瞬态窗外的新增=活跃驱动内存故障；首条：$(journalctl -k --since "${_boot_end:-$_gate_since}" --no-pager 2>/dev/null | grep -m1 'NV_ERR_NO_MEMORY' | tail -c 160))"
  else
    ok "NV_ERR_NO_MEMORY 稳态期=0（启动窗瞬态 ${_nverr_boot:-0} 条=图捕获分配重试已知态；本靴累计 ${_nverr_all:-0}）"
  fi
else
  bad "journalctl -k 不可读（权限/环境变化）——NV_ERR 无法判定，勿当作零事件"
fi
# ── 2026-09-20 H4：启动期静默失效面解析（读 head 容器日志，零镜像变更） ──
# 三类"只打印不拦"的失效此前全靠人翻日志：warmup 失败档（首请求付冷路径）、批乱码
# WARNING（09-11 bs≥3 NaN 实录=最危险的绿灯放行）、SPS 表缺失静默降级 verify-all
# （投机收益归零而所有门全绿——0.2.6 在役实例即此态）。镜像内 boot.py 落
# state/warmup.json 的版本合批 0.2.7，本版先以日志解析闭环。
_ctn="${HEAD_CTN:-dsv41-head}"
# ── 2026-09-21 0.2.7：boot.py 落 state/warmup.json ⇒ 优先机读文件（存在且晚于
# 本次容器启动才采信），0.2.6 及更早靴自动回退日志解析。两分支判定口径一致。──
_wjson="${STATE_DIR:-$HOME/dsv41-flash-dgxsparks/state}/warmup.json"
_wsummary=""
if [ -f "$_wjson" ]; then
  _boot_ts=$(docker inspect -f '{{.State.StartedAt}}' "$_ctn" 2>/dev/null || true)
  _wsummary=$(python3 - "$_wjson" "$_boot_ts" <<'PY' 2>/dev/null || true
import json, os, sys
from datetime import datetime
path, boot = sys.argv[1], sys.argv[2]
try:
    j = json.load(open(path))
except Exception as e:
    print(f"JSON-ERR {e}"); raise SystemExit
if boot:
    try:
        bt = datetime.fromisoformat(boot.replace('Z', '+00:00')).timestamp()
        if os.stat(path).st_mtime < bt:
            print("STALE"); raise SystemExit
    except ValueError:
        pass
sizes = j.get('sizes') or []
batch = j.get('batch') or {}
print("WARMUP-JSON ok=%s size_fails=%d batch_fails=%s batch_garbled=%s total_s=%s" % (
    j.get('ok'), sum(1 for s in sizes if not s.get('ok')),
    batch.get('failures'), batch.get('garbled'), j.get('total_s')))
PY
)
fi
if docker inspect "$_ctn" >/dev/null 2>&1; then
  if [[ "$_wsummary" == WARMUP-JSON* ]]; then
    _g=$(sed -n 's/.*batch_garbled=\([0-9]*\).*/\1/p' <<<"$_wsummary")
    _f=$(sed -n 's/.*size_fails=\([0-9]*\).*/\1/p' <<<"$_wsummary")
    _bf=$(sed -n 's/.*batch_fails=\([0-9]*\).*/\1/p' <<<"$_wsummary")
    # 审计 P3 修：boot.py 未落 batch_fails 字段时 sed 提空 → `-gt 0` 按 0 计=缺数据当绿。
    # 空值归一 NA 并在告警文案中明示，与「真 0」区分。
    [[ -z "${_bf:-}" ]] && _bf=NA
    if [ "${_g:-0}" -gt 0 ] || [ "${_bf:-0}" != NA ] && [ "${_bf:-0}" -gt 0 ]; then
      bad "warmup.json：批乱码 ${_g} / 批失败 ${_bf}（并发批在产出垃圾或失败——bs≥3 NaN 史，profile-2026-09-10 §16；$_wsummary）"
    elif [ "${_f:-0}" -ge 2 ]; then
      bad "warmup.json：失败档 ×${_f}（≥2 档失败=首请求冷路径风险；$_wsummary）"
    elif [ "${_f:-0}" -eq 1 ]; then
      ok "warmup.json：失败档 ×1（单档可容忍；$_wsummary）"
    else
      ok "warmup.json：零失败档 + 批 sanity 无告警（$_wsummary）"
    fi
    _sps_miss=$(docker logs "$_ctn" 2>&1 | grep -c 'DSPARK_SPS_TABLE=.* not found')
    # 2026-09-21 白盒修正：旧版这里 _wlog="" ⇒ 下方 NCCL WARN 扫描对空输入恒 0，
    # 「NCCL 零 WARN」在 0.2.7（warmup.json 分支）必假 PASS——静默跳过 NCCL 断言。
    # json 分支仍要抓容器日志供 NCCL/告警扫描用（warmup 判定读 json，日志归日志）。
    _wlog=$(docker logs "$_ctn" 2>&1)
  else
  _wlog=$(docker logs "$_ctn" 2>&1)
  _garbled=$(printf '%s' "$_wlog" | grep -c 'BATCH OUTPUT SANITY CHECK FAILED')
  _wu_fail=$(printf '%s' "$_wlog" | grep -c 'warm-up prompt (.*) failed:')
  _sps_miss=$(printf '%s' "$_wlog" | grep -c 'DSPARK_SPS_TABLE=.* not found')
  if [ "${_garbled:-0}" -gt 0 ]; then
    bad "启动批乱码 WARNING ×${_garbled}（并发批在产出垃圾——bs≥3 NaN 史，profile-2026-09-10 §16；样本：$(printf '%s' "$_wlog" | grep -m1 -A1 'BATCH OUTPUT SANITY CHECK FAILED' | tail -c 120)）"
  elif [ "${_wu_fail:-0}" -ge 2 ]; then
    bad "warmup 失败档 ×${_wu_fail}（≥2 档失败=首请求冷路径风险；docker logs ${_ctn} 查明细）"
  elif [ "${_wu_fail:-0}" -eq 1 ]; then
    ok "warmup 失败档 ×1（单档可容忍，已留痕 docker logs）"
  else
    ok "warmup 零失败档 + 批 sanity 无告警"
  fi
  fi
  if [ "${_sps_miss:-0}" -gt 0 ]; then
    ok "SPS 表缺失 → verify-all 降级在役（static 模式下 no-op 属已知态；收益型降级留痕，0.2.7 随 warmup.json 闭环）"
  else
    ok "SPS 表在位（无降级行）"
  fi
  # ── 2026-09-20 H8：NCCL 运行面断言（容器 env 形态 + WARN 行扫描）──
  # 生产 NCCL_DEBUG=WARN 时健康靴零输出 ⇒ 任何 "NCCL WARN" 都是真信号；env 形态
  # 断言拦「EXTRA_DOCKER_ENV 回归/漏注入 LD_PRELOAD」这类静默走错通信栈的失效
  # （ring-only 退化/SHM 回退只会更慢不会报错——形态对了才敢信带宽）。
  _nenv=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$_ctn" 2>/dev/null)
  _nshape=0
  printf '%s\n' "$_nenv" | grep -q '^NCCL_ALGO=RING$'       || { bad "容器缺 NCCL_ALGO=RING（EXTRA_DOCKER_ENV 回归？环网算子形态漂移）"; _nshape=1; }
  printf '%s\n' "$_nenv" | grep -q '^NCCL_NET_PLUGIN=none$' || { bad "容器缺 NCCL_NET_PLUGIN=none（netdev 硬编码插件未生效）"; _nshape=1; }
  printf '%s\n' "$_nenv" | grep -q '^NCCL_MIN_NCHANNELS='   || { bad "容器缺 NCCL_MIN_NCHANNELS（通道数下限旋钮未注入）"; _nshape=1; }
  if [ "${_nshape:-1}" = 0 ]; then
    ok "NCCL env 形态（ALGO=RING/NET_PLUGIN=none/MIN_NCHANNELS 在位）"
  fi
  _ncclwarn=$(printf '%s' "$_wlog" | grep -c 'NCCL WARN')
  if [ "${_ncclwarn:-0}" -gt 0 ]; then
    bad "容器日志 NCCL WARN ×${_ncclwarn}（ring-only 健康靴零输出，任何 WARN 都是真信号；首条：$(printf '%s' "$_wlog" | grep -m1 'NCCL WARN' | tail -c 140)）"
  else
    ok "NCCL 零 WARN（健康态）"
  fi
else
  # 审计 P1 修：inspect 失败时上四族断言一条都没跑——静默无输出会被当「差不多绿」。
  # 检查跑不了=FAIL，不是 PASS（fail-closed 教义）。
  bad "docker inspect $_ctn 失败（容器名错/docker socket 权限丢失/daemon 死？）——warmup/SPS/NCCL 四族断言未执行≠通过"
fi

# ── GPU 时钟健康（2026-09-21 定谳的 GB10「PD 安全模式」病；NVIDIA 论坛同款 721MHz 病）──
# 病征：断电/OOM 事件后 USB-C 电源 PD 协商进安全模式，SM 时钟钉死 513-728MHz
# （P0、96% util、~15-20W、零 throttle 标志、-lgc 无效、warm reboot 无效）。
# 本集群 2026-09-21 实锤：某台 worker 钉 721MHz ⇒ TP4 全体 prefill 减半（5000→2500 t/s）。
# 唯一修复=拔墙上插座冷断电 1-2 分钟（社区多帖确认；拔机箱端 USB-C 无效）。
# 判别=gate 的 bench 载荷下采样：util 高而时钟 <1200MHz 即判（健康负载态 2380-2400）。
_clk_bad=0
# 审计 P1 修：nvidia-smi 挂掉（驱动死/NVML 故障——断电后正是目标场景）时旧逻辑
# `2>/dev/null` 吞错→空输出→默认值兜底→条件恒假→假绿「采样完成」。
# 工具不可读=无法判定=FAIL，不是 PASS。
if ! nvidia-smi -L >/dev/null 2>&1; then
  bad "nvidia-smi 不可读（驱动/NVML 故障？）——时钟健康无法判定≠通过；断电后驱动半死是本检查的目标场景，人工复核"
  _clk_bad=1
fi
for _s in 1 2 3; do
  read -r _u _c _p < <(nvidia-smi --query-gpu=utilization.gpu,clocks.sm,power.draw --format=csv,noheader,nounits 2>/dev/null | awk -F'[ ,%W]+' '{print $1, $2, $3}')
  if [ "${_u:-0}" -ge 50 ] && [ "${_c:-9999}" -lt 1200 ]; then
    bad "GPU 时钟楔死嫌疑：util=${_u}% clock=${_c}MHz power=${_p}W（PD 安全模式：负载态应 2380+MHz/40W+；修复=冷断电，见 ~/w6-kit/FABRIC-GID-REPAIR-RUNBOOK.md §7）"
    _clk_bad=1
    break
  fi
  sleep 3
done
# 采样窗可能撞不上高 util（引擎空转）——空转态退而求其次看时钟地板异常抬升不了的形态没意义，
# 只在高 util 撞上时才判负；三窗全空转记 INFO 级（ok）避免假阳。
# 审计 P2 修（诚实文案）：本快档只采 head 一机——2026-09-21 事故机恰是 worker 02，
# worker 覆盖靠 --full 的 canary 载荷窗四机采样，快档结论不冒充四机。
[ $_clk_bad = 0 ] && ok "GPU 时钟健康采样完成（head 一机；未观测负载态低频楔死。worker 三机由 gate --full canary 载荷窗覆盖）"

# ── autotune golden 锁定断言（2026-09-21 用户指令：健康缓存+锁定+重建质量门）──
# 三层：①挂载在场（没挂=绕过锁定，退回镜像烘焙表+每靴 1/4 票决覆写的偶然锁）
# ②宿主 golden 树与 MANIFEST 逐文件 md5 一致（防漂移/防静默篡改）
# ③manifest 外新键目录=配置变更后的冷签已落地宿主——必须走重建规程（质量门），
#   否则一张未经判定的战术表就自封 golden。worker 侧同树由 rsync 对齐保证。
_GOLDEN="$HOME/dsv41-flash-dgxsparks/autotune-golden"
if [[ -d "$_GOLDEN/data" ]]; then
  _gm_bad=0
  docker inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$_ctn" 2>/dev/null | grep -qF "$_GOLDEN/data" \
    || { bad "autotune golden 未挂载进 $_ctn（start.sh golden_mounts 未生效——锁定被绕过）"; _gm_bad=1; }
  if [[ -f "$_GOLDEN/MANIFEST.json" ]]; then
    while read -r f; do
      rel=${f#$_GOLDEN/data/}
      _want=$(python3 -c "import json,sys;rel=sys.argv[1];print(json.load(open('$_GOLDEN/MANIFEST.json'))['keys'][rel.split('/')[2]]['file_md5'][rel.split('/')[-1]])" "$rel" 2>/dev/null)
      _got=$(md5sum "$f" | cut -d' ' -f1)
      [[ "$_want" = "$_got" ]] || { bad "golden 漂移：data/$rel md5=$_got ≠ manifest ${_want:-<无此条目>}（表被改/冷签写入/manifest 漏收）"; _gm_bad=1; }
    done < <(find "$_GOLDEN/data" -name 'rank_tp*.json' | sort)
    for _d in "$_GOLDEN/data"/*/*/*/; do
      _k=$(basename "$_d")
      grep -q "\"$_k\"" "$_GOLDEN/MANIFEST.json" || { bad "golden 出现 manifest 外新键 $_k（缓存键变更：冷签已落地——按 AUTOTUNE-GOLDEN-RUNBOOK.md 质量门重建后再收录）"; _gm_bad=1; }
    done
  else
    bad "golden data 在但 MANIFEST.json 缺失（无法断言一致性）"
    _gm_bad=1
  fi
  [[ $_gm_bad = 0 ]] && ok "autotune golden 锁定在役（挂载在场 + manifest 逐文件一致）"
elif [[ -f "$_GOLDEN/DISABLED" ]]; then
  ok "autotune golden 显式停用（DISABLED 标记在场）——镜像烘焙表+每靴票决形态，运维知悉"
else
  # 审计 P2 修：目录意外缺失（rsync 误删/HOME 漂移/路径改名）与「主动不启用」在
  # 门禁视角同形——锁定被绕过不能静默绿。显式 touch autotune-golden/DISABLED 才允许不锁。
  bad "autotune golden 树缺失且无 DISABLED 标记（意外缺失还是主动停用？启用/重建见 autotune-golden/MANIFEST.json 与 AUTOTUNE-GOLDEN-RUNBOOK.md；确要停用：touch $_GOLDEN/DISABLED）"
fi

# ── 现役形态解析（2026-09-22 加）─────────────────────────────────────────────
# 旧版 overlay md5 块靠 ${SGLANG_CODE_MOUNTS}/${SGLANG_OVERLAY_DIR} 是否出现在 gate 进程的
# env 里判定要不要跑；而 start.sh 不 export 这两个变量（唯一调用点是 start.sh:1661 起的子进程）
# ⇒ 裸跑 gate.sh 时两者恒空，整块断言**从未执行且不留任何痕迹**——与「恒假 PASS」同族。
# 改成两级**真身**取证：
#   ① 声明：launch-banner.log 最近一次 serve 的 ENV_FILE → 该 env 文件的 CODE_MOUNTS/OVERLAY_DIR
#   ② 实际：容器挂载表里有没有 /sgl-workspace/sglang/** 的逐文件挂载源（比声明硬）
# 声明有、实际无 = 形态漂移 ⇒ FAIL；两者都无 = 生产镜像形态 ⇒ **显式打印不适用**（不冒充通过）。
_gate_ctn="${HEAD_CTN:-dsv41-head}"
_gate_st="${STATE_DIR:-$HOME/dsv41-flash-dgxsparks/state}"
_gate_envf=$(grep -o 'ENV_FILE=[^ ]*' "$_gate_st/launch-banner.log" 2>/dev/null | tail -1 | cut -d= -f2)
_gate_exp_ov=0; _gate_ov_dir=""
if [[ -n "${_gate_envf:-}" ]]; then
  _gate_envp="$_gate_envf"; [[ "$_gate_envf" = /* ]] || _gate_envp="$HOME/dsv41-flash-dgxsparks/$_gate_envf"
  if [[ -f "$_gate_envp" ]]; then
    [[ "$(grep -m1 -E '^SGLANG_CODE_MOUNTS=' "$_gate_envp" | cut -d= -f2)" = "1" ]] && _gate_exp_ov=1
    _gd=$(sed -n 's/^SGLANG_OVERLAY_DIR=//p' "$_gate_envp" | head -1)
    [[ -n "$_gd" ]] && _gate_ov_dir="${_gd/\$HOME/$HOME}"
  else
    bad "launch-banner 记的 ENV_FILE=$_gate_envf 在仓库里不存在 —— 现役形态判定失去依据（勿当作生产形态）"
  fi
fi
_gate_ov_mnt=$(docker inspect "$_gate_ctn" -f '{{range .Mounts}}{{.Source}}|{{.Destination}}{{"\n"}}{{end}}' 2>/dev/null | awk -F'|' '$2 ~ /^\/sgl-workspace\/sglang\//{print $1; exit}')
_gate_live_ov=0
if [[ -n "$_gate_ov_mnt" ]]; then _gate_live_ov=1; _gate_ov_dir=$(dirname "$_gate_ov_mnt"); fi
if [[ "$_gate_exp_ov" = 1 && "$_gate_live_ov" = 0 ]] && docker inspect "$_gate_ctn" >/dev/null 2>&1; then
  bad "形态漂移：$_gate_envf 声明 SGLANG_CODE_MOUNTS=1 但容器里没有 /sgl-workspace/sglang 逐文件挂载（挂载丢失/容器起自另一形态）"
fi

# ── 2026-09-22 审计 P1-1 收尾：代码 overlay 容器内 md5 断言（内容级） ──
# start.sh 的熔断只数「挂载个数」（计数级）；9/21 split-brain 教训=宿主侧
# md5 ×4 一致查不出容器挂载分叉（单文件 bind-mount 钉 inode）。这里直接进
# 四机容器比对每个挂载文件的字节：跨 rank 不一致=split-brain（拒交付）；
# 一致但 ≠ 宿主当前字节=重启前旧 inode（合法，提示不拦）。
_ov_ctn_bad=0; _ov_stale=0
if [[ "$_gate_live_ov" = 1 && -n "${_gate_ov_dir:-}" && -d "${_gate_ov_dir:-}" ]]; then
  _CTN_PREFIX=/sgl-workspace/sglang
  while read -r _ok_key _ok_rel; do
    [[ -f "$_gate_ov_dir/$_ok_key" ]] || continue
    _cpath="$_CTN_PREFIX/$_ok_rel"
    _md5_head=$(docker exec "$_gate_ctn" md5sum "$_cpath" 2>/dev/null | cut -d" " -f1)
    [ -z "$_md5_head" ] && { bad "overlay 容器内缺挂载：$_cpath（head 容器内无此文件——map 与容器布局漂移）"; _ov_ctn_bad=1; continue; }
    for _ow in $_WORKERS; do
      # 2026-09-22：半死 worker（TCP accept 但不出 banner，9/21-22 楔死实测形态）会让裸 ssh
      # 无限等 banner ⇒ **门禁整体挂死**。加连线+保活双上限，退化为 8-14s 内判红。
      _md5_w=$(ssh -o BatchMode=yes -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 \
        "$_ow" "docker exec dsv41-worker md5sum $_cpath 2>/dev/null" | cut -d" " -f1)
      if [ -z "$_md5_w" ]; then
        bad "overlay 容器内缺挂载：$_cpath（$_ow worker 容器内无此文件——split-brain）"; _ov_ctn_bad=1
      elif [ "$_md5_w" != "$_md5_head" ]; then
        bad "overlay 容器内 md5 分叉：$_cpath head=$_md5_head ${_ow}=$_md5_w（四机 rank 读不同字节=split-brain）"; _ov_ctn_bad=1
      fi
    done
    _md5_host=$(md5sum "$_gate_ov_dir/$_ok_key" | cut -d" " -f1)
    [ "$_md5_host" != "$_md5_head" ] && _ov_stale=$((_ov_stale+1))
  done < <(awk '/^declare -A SGLANG_OVERLAY_MAP=\(/,/^\)/' "$ROOT/start.sh" | sed -n 's/^[[:space:]]*\[\([^]]*\)\]=\([^[:space:]]*\).*/\1 \2/p')
  if [ "$_ov_ctn_bad" = 0 ]; then
    if [ "$_ov_stale" -gt 0 ]; then
      ok "overlay 容器内 md5 四机一致（$_ov_stale 个文件宿主已更新待下靴生效=旧 inode 合法态）"
    else
      ok "overlay 容器内 md5 四机一致且与宿主同字节"
    fi
  fi
elif [[ "$_gate_live_ov" = 0 && "$_gate_exp_ov" = 0 ]]; then
  ok "overlay 容器内 md5 断言：本次为镜像形态（无逐文件挂载，${_gate_envf:-无 ENV_FILE 记录}）——按设计不适用"
else
  ok "overlay 容器内 md5 断言：容器不可判（inspect 失败或形态未定）——见上方形态漂移项"
fi

# ── 2026-09-22 客户 bug 防线：mm 占位符禁集「生效性」断言（审计 B §7 必交付项）──
# 三层判据，任一不满足即 FAIL（不冒充通过）：
#   ① 容器内代码必须含禁集补丁（宿主该形态带补丁而容器不带 = 未生效/旧 inode ⇒ FAIL）
#   ② 日志必须出现 `mm-ban: 已从采样概率排除 <N>`，且 N==按容器 env 开关算出的期望
#      （组1 425 + 组2 13；任一被显式关掉则期望相应减少 —— 防止「补丁在但没跑过」）
#   ③ `MM_BAN_APPLY_FAILED` 计数必须 =0（宽度不足/屏蔽抛错都打这个串，fail-open 的第三态）
#   ④ 加载期自检 `mm-ban self-check OK` 必须在场（2026-09-22 加固版新增；缺=跑的旧字节）
_mm_model_rel=python/sglang/srt/models/deepseek_v4.py
_mm_ctn_ban=0; _mm_host_ban=0
if docker inspect "$_gate_ctn" >/dev/null 2>&1; then
  _mm_ctn_ban=$(docker exec "$_gate_ctn" grep -c 'MM_BAN_APPLY_FAILED' "/sgl-workspace/sglang/$_mm_model_rel" 2>/dev/null || echo 0)
  [[ -n "${_gate_ov_dir:-}" && -f "$_gate_ov_dir/deepseek_v4_model.py" ]] && \
    _mm_host_ban=$(grep -c 'MM_BAN_APPLY_FAILED' "$_gate_ov_dir/deepseek_v4_model.py" 2>/dev/null || echo 0)
  if [ "${_mm_ctn_ban:-0}" -ge 1 ]; then
    _mmlog=$(docker logs "$_gate_ctn" 2>&1)
    _mm_n_hit=$(printf '%s' "$_mmlog" | grep -c 'mm-ban: 已从采样概率排除')
    _mm_n_ids=$(printf '%s' "$_mmlog" | grep -o 'mm-ban: 已从采样概率排除 [0-9]*' | head -1 | grep -o '[0-9]*$')
    _mm_n_fail=$(printf '%s' "$_mmlog" | grep -c 'MM_BAN_APPLY_FAILED')
    _mm_n_sc=$(printf '%s' "$_mmlog" | grep -c 'mm-ban self-check OK')
    # 期望值：按**容器 env**（真身）算，不写死 438——关了组就少，但 gate 会看到并记录
    _mm_env=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$_gate_ctn" 2>/dev/null)
    _mm_want=0
    printf '%s\n' "$_mm_env" | grep -qE '^DSV41_BAN_MM_PLACEHOLDERS=(0|false|no|off)$' || _mm_want=$((_mm_want+425))
    printf '%s\n' "$_mm_env" | grep -qE '^DSV41_BAN_PROMPT_CONTROL_TOKENS=(0|false|no|off)$' || _mm_want=$((_mm_want+13))
    _mm_bad=0
    if [ "${_mm_n_hit:-0}" -eq 0 ]; then
      bad "mm 禁集补丁在容器内但**从未执行**（日志无「mm-ban: 已从采样概率排除」行）——补丁在≠防护在"; _mm_bad=1
    elif [ "${_mm_n_ids:-0}" != "$_mm_want" ]; then
      bad "mm 禁集生效数 ${_mm_n_ids:-?} ≠ 期望 $_mm_want（组1 425 + 组2 13，按容器 env 开关算）——id 表漂移或开关被改"; _mm_bad=1
    fi
    if [ "${_mm_n_fail:-0}" -gt 0 ]; then
      bad "MM_BAN_APPLY_FAILED ×${_mm_n_fail}（禁集未生效：窄词表路径/屏蔽抛错；首条：$(printf '%s' "$_mmlog" | grep -m1 'MM_BAN_APPLY_FAILED' | tail -c 150)）"; _mm_bad=1
    fi
    if [ "${_mm_n_sc:-0}" -eq 0 ]; then
      bad "缺加载期自检行「mm-ban self-check OK」（容器内是加固前旧字节 ⇒ 机制未经断言）"; _mm_bad=1
    fi
    [ "${_mm_bad:-0}" = 0 ] && ok "mm 禁集生效：排除 ${_mm_n_ids} 列（期望 $_mm_want）+ 加载期自检 OK + 零 MM_BAN_APPLY_FAILED"
    # ⑤ 集合语义防漂移（审计 B「校验器进 gate」）：把现役形态里的 id 表与 tokenizer/模型声明对表。
    #    红=硬编码集合与语义不符（改了一侧/擅自加区间/gen 时手滑）。该失效**不留任何日志痕迹**
    #    （数量仍 438、自检仍过——因为自检只验机制一致，不验语义），只能靠对表抓。
    _mm_tok="${MM_BAN_TOKENIZER:-/data/models/DeepSeek-V4.1-Flash/tokenizer.json}"
    if [[ "${_mm_host_ban:-0}" -ge 1 && -n "${_gate_ov_dir:-}" && -f "$_gate_ov_dir/deepseek_v4_dspark.py" && -f "$_mm_tok" ]]; then
      _mm_vout=$(python3 "$ROOT/scripts/verify_mm_ban_set.py" "$_mm_tok" \
        "$_gate_ov_dir/deepseek_v4_model.py" "$_gate_ov_dir/deepseek_v4_dspark.py" 2>&1); _mm_vrc=$?
      if [ "$_mm_vrc" = 0 ]; then
        ok "mm 禁集集合语义对表通过（$(printf '%s' "$_mm_vout" | grep -o '合计 [0-9]* + [0-9]* = [0-9]* 个 id' | head -1)）"
      else
        bad "mm 禁集集合语义漂移（校验器 rc=$_mm_vrc）：$(printf '%s' "$_mm_vout" | grep -m1 -E 'FAIL|⛔' | cut -c1-160)"
      fi
    elif [[ "${SGLANG_MM_REQUIRE_VERIFY:-0}" = 1 ]]; then
      bad "mm 禁集校验器未跑（缺 tokenizer 或两件不齐）：dir=${_gate_ov_dir:-空} tok=$_mm_tok —— 集合漂移无法排除"
    else
      ok "mm 禁集集合对表：本次无可对的文件（形态不含补丁）——按设计不适用"
    fi
  elif [ "${_mm_host_ban:-0}" -ge 1 ]; then
    bad "mm 禁集：宿主形态 $_gate_ov_dir 已带补丁但容器内代码没有（未重启/挂载丢失）——本次服务无该防护"
  else
    ok "mm 禁集断言：本次形态不含该补丁（非发货形态；生产镜像形态由 0.2.7 后合批，A/B 臂按设计无）"
  fi
else
  bad "mm 禁集断言无法执行：docker inspect $_gate_ctn 失败（容器名错/daemon 死？）"
fi


# 2026-09-19 外部报告借鉴：引擎 /health 写死 1s 延迟，探活改 /v1/models（同 200 判定，快 ~1000×）
if curl -fsS --max-time 10 "${auth[@]}" "$BASE/v1/models" >/dev/null 2>&1 \
   || curl -fsS --max-time 10 "$BASE/v1/models" >/dev/null 2>&1; then
  ok "engine /v1/models 200"
else
  bad "engine /v1/models 非 200 —— 服务不可交付"
fi

# ── 2. 算术（贪心确定性） ──────────────────────────────────────────────────
r=$(ask '{"model":"deepseek-v4.1-flash","temperature":0,"max_tokens":16,
  "chat_template_kwargs":{"thinking":false},
  "messages":[{"role":"user","content":"What is 19 + 23? Reply only the number."}]}')
if printf '%s' "$r" | python3 -c 'import json,sys
try:
    sys.exit(0 if json.load(sys.stdin)["choices"][0]["message"]["content"].strip() == "42" else 1)
except Exception:
    sys.exit(1)' 2>/dev/null; then
  ok "算术 19+23=42"
else
  bad "算术失败: ${r:0:120}"
fi

# ── 3. 结构化输出 ──────────────────────────────────────────────────────────
r=$(ask '{"model":"deepseek-v4.1-flash","temperature":0,"max_tokens":64,
  "chat_template_kwargs":{"thinking":false},
  "response_format":{"type":"json_schema","json_schema":{"name":"a","strict":true,
    "schema":{"type":"object","properties":{"answer":{"type":"integer"}},
              "required":["answer"],"additionalProperties":false}}},
  "messages":[{"role":"user","content":"Return an object whose answer is the integer 42."}]}')
if printf '%s' "$r" | python3 -c 'import json,sys
try:
    c = json.load(sys.stdin)["choices"][0]["message"]["content"]
    sys.exit(0 if json.loads(c) == {"answer": 42} else 1)
except Exception:
    sys.exit(1)' 2>/dev/null; then
  ok "JSON schema 结构化输出"
else
  bad "结构化失败: ${r:0:120}"
fi

# ── 4. 工具调用 ────────────────────────────────────────────────────────────
r=$(ask '{"model":"deepseek-v4.1-flash","temperature":0,"max_tokens":96,
  "chat_template_kwargs":{"thinking":false},
  "tools":[{"type":"function","function":{"name":"lookup","description":"get value",
    "parameters":{"type":"object","properties":{"key":{"type":"string"}},
                  "required":["key"],"additionalProperties":false}}}],
  "messages":[{"role":"user","content":"Use lookup to get the value for key alpha. Do not guess."}]}')
if printf '%s' "$r" | python3 -c 'import json,sys
try:
    t = json.load(sys.stdin)["choices"][0]["message"].get("tool_calls") or []
    sys.exit(0 if (len(t) == 1 and t[0]["function"]["name"] == "lookup"
                   and json.loads(t[0]["function"]["arguments"]) == {"key": "alpha"}) else 1)
except Exception:
    sys.exit(1)' 2>/dev/null; then
  ok "工具调用（tool_calls，参数正确）"
else
  bad "工具调用失败: ${r:0:160}"
fi

# ── 5/6. corruption + code-gate（复用 gates_suite，容器内跑） ───────────────
# gates_suite.py 必须在 /state（= 宿主 state-tp4/）里，否则下面这三档会**静默跳过**。
# 历史教训：那段"跳过"曾经一挂就是很多天——W3 记录里 /state 从来没有过这个工件，而
# gate.sh 照报"GATE PASSED（4 项）"，看不出深档根本没跑。所以：能自动落位就落位，
# 落不了位就判**失败**（判据跑不起来本身就是失败，不是"跳过"）。
SUITE_SRC="$HOME/dsv41-flash-dgxsparks/bench/gates_suite.py"
# ★2026-09-18 布局自适应：/state 的宿主真身有两个时代——state-tp4/（09-17 前）与
# state/（S5/SD-1 会话起）。两个目录都落位，以 docker 实际挂载为准。
if [[ -f "$SUITE_SRC" ]] && ! docker exec dsv41-head test -f /state/gates_suite.py 2>/dev/null; then
  _ST_MNT=$(docker inspect dsv41-head --format '{{range .Mounts}}{{.Source}} {{.Destination}}{{"\n"}}{{end}}' 2>/dev/null | awk '$2=="/state"{print $1}')
  for _d in "$HOME/dsv41-flash-dgxsparks/state-tp4" "$HOME/dsv41-flash-dgxsparks/state" "${_ST_MNT:-}"; do
    [[ -n "$_d" && -d "$_d" ]] && cp "$SUITE_SRC" "$_d/gates_suite.py" 2>/dev/null
  done
  echo "[*] 已把 gates_suite.py 落位（state-tp4/ + state/；容器实际挂载=${_ST_MNT:-?}）"
fi
if docker exec dsv41-head test -f /state/gates_suite.py 2>/dev/null; then
  out=$(timeout 600 docker exec -w /state dsv41-head python3 /state/gates_suite.py --corruption --code --key "$KEY" 2>&1)
  if echo "$out" | grep -q 'U+FFFD=0' && ! echo "$out" | grep -q 'FAIL'; then
    ok "corruption probe 0/0/0"
  else
    bad "corruption 异常: $(echo "$out" | grep -m1 'U+FFFD' || echo 无输出)"
  fi
  if echo "$out" | grep -q 'code-gate total: 12/12'; then
    ok "code-gate 12/12"
  else
    bad "code-gate: $(echo "$out" | grep -m1 'code-gate total' || echo 未完成)"
  fi
else
  bad "gates_suite 不在容器内（深档 corruption/code-gate 跑不了；判据缺失≠通过）"
fi

# ── 全档：终止性 + needle 梯度 ─────────────────────────────────────────────
if [[ "$FULL" -eq 1 ]]; then
  out=$(timeout 600 docker exec -w /state dsv41-head python3 /state/gates_suite.py --termination --key "$KEY" 2>&1)
  if [[ "$(echo "$out" | grep -c '18/18 stop')" -eq 2 ]]; then ok "终止性 18/18 · 18/18"
  else bad "终止性: $(echo "$out" | tr '\n' ' ')"; fi

  # ── 2026-09-21 防冻结看门狗（01 全档 OOM 卡死教训）：终态 ctx=147456，
  # >128K 单流被引擎 HTTP 400 结构性拒绝（安全垫回归诚实边界）；
  # 229K/470K needle 走 EXEMPT 档（gates_suite 逐档捕获 400，不再炸整 suite）。
  # 看门狗仍保留：MemAvailable 跌破中止线即杀 needle 客户端并判 FAIL——宁可门红，不可主机死。
  _avail_mib() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }
  # 2026-09-21 分层修正：引擎 UM 驻留后 head 的 MemAvailable 天然贴 8GiB 线摆动
  # （实测 7838-8139MiB），一刀切 8GiB 使安全形态下的 gate 变掷硬币。防线本意=
  # 防「真会分配大缓冲」的 needle：ctx<229376 时 229K/470K 进门即 HTTP 400
  # （不分配），真跑的只有 30K（~百 MB 级）⇒ 地板降为看门狗同款 5GiB；
  # ctx≥229376（大档真跑）保持 8GiB 冻结事故硬线不动。
  _ctx=$(grep -oE 'ctx=[0-9]+' "$HOME/dsv41-flash-dgxsparks/state/launch-banner.log" 2>/dev/null | tail -1 | grep -oE '[0-9]+')
  _floor=8192
  [[ -n "${_ctx:-}" && "$_ctx" -lt 229376 ]] && _floor=5120
  if [[ "$(_avail_mib)" -lt "$_floor" ]]; then
    bad "needle 前置内存门：MemAvailable=$(_avail_mib)MiB < $(( _floor / 1024 ))GiB（ctx=${_ctx:-?} 档地板；引擎驻留后余量不足，拒绝发起 needle——冻结事故防线）"
    # 审计 P2 修：内存门 trip 后 out 仍是 corruption/code-gate 阶段旧值，下方判据
    # 会拿 12 条 code-gate PASS 行拼出「needle 全 PASS」的自相矛盾绿——消毒。
    out="（内存门拒绝发起，needle 未跑）"
  else
    timeout 1800 docker exec -w /state dsv41-head python3 /state/gates_suite.py --needle --key "$KEY" > /tmp/gate-needle.out 2>&1 &
    _npid=$!
    ( while kill -0 "$_npid" 2>/dev/null; do
        _m=$(_avail_mib)
        if [[ $_m -lt 5120 ]]; then
          echo "[gate] MemAvailable=${_m}MiB < 5GiB —— 中止 needle 客户端" >> /tmp/gate-needle.out
          kill -9 "$_npid" 2>/dev/null
          pkill -f 'gates_suite.py --needle' 2>/dev/null
          # 审计 P2 修：宿主侧只杀得掉 docker exec 客户端，容器内 gates_suite 仍在
          # 发后续档请求——补容器内侧杀，兑现「宁可门红不可主机死」的另一半。
          docker exec "$_ctn" pkill -f 'gates_suite.py --needle' 2>/dev/null
          break
        fi
        sleep 2
      done ) &
    _wdpid=$!
    wait "$_npid"; _nrc=$?
    kill "$_wdpid" 2>/dev/null
    wait "$_wdpid" 2>/dev/null
    out=$(cat /tmp/gate-needle.out)
    if grep -q '中止 needle 客户端' /tmp/gate-needle.out 2>/dev/null; then
      bad "needle 看门狗中止：主机 MemAvailable 跌破 5GiB（ec 保护未生效或负载超限——禁止重试，先查 reserved 内存曲线）"
    fi
  fi
  # 判据（2026-09-21 终态版）：ctx=147456 ⇒ 30K 必 PASS（包络内证明）；
  # 229K/470K 预期 HTTP 400 EXEMPT（安全垫生效）。三档必须全部有结论
  # （PASS 或 EXEMPT），任何一档真 FAIL、或 30K 非 PASS、或档位缺失即失败。
  n_pass=$(printf '%s' "$out" | grep -c ' PASS')
  n_ex=$(printf '%s' "$out" | grep -c 'EXEMPT')
  n_depth=$(printf '%s' "$out" | grep -c '^needle ')
  if [[ "$n_pass" -ge 3 ]]; then
    ok "needle 30K/229K/470K 全 PASS"
  elif [[ "${_nrc:-1}" -eq 0 && "$n_depth" -eq 3 ]] && \
       printf '%s' "$out" | grep -q '^needle 30000:.* PASS'; then
    # 审计 P0 修：旧判据 `n_pass+n_ex==n_depth` 对 depth=1/2 平凡成立——gates_suite
    # 在非 400 异常（超时/连接重置）时直接 raise、后续档不再打印，30K PASS 后 229K
    # 挂死（=01 冻结事故形态）时只剩 1 行输出 → 1+0==1 假绿还谎称「安全垫生效」。
    # 硬条件：套件退出码 0 + 三档全部有结论（gates_suite 逐档捕获 400 走 EXEMPT，
    # 其它异常会 raise → rc≠0 或 depth<3 → 红）。
    ok "needle 30K PASS（包络内）+ 超包络档结论 ×${n_ex}（安全垫生效=ctx=147456 终态）"
  else
    bad "needle（rc=${_nrc:-?} 档数=${n_depth}/3）：$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"
  fi
fi

# ── perf canary（--full 专属·2026-09-21 门禁统筹：prefill 2× 回归的常设哨兵）──
# 口径同 PRv3：纯 prefill（max_tokens=1）单流 8192 档，flush 后计时，地板 4500 t/s
# （V4B 健康锚 4992；2026-09-21 事故带 2210-2821 = 02 时钟楔死所致）。
# 自动分诊第一层内建：canary 载荷窗内四机并行采样 SM 时钟，命中
# util≥50%&&clock<1200MHz 的机器直接点名（PD 安全模式），否则按序指向
# fabric / autotune golden / 手册。诊断树出处=2026-09-21 排查链。
if [[ "$FULL" -eq 1 ]]; then
  # 2026-09-21 canary 定稿：直接调 PRv3 采集器本体（PREFILL_SIZES=8192 CONCURRENCIES=1）。
  # ★为什么不用自研哨兵请求：三天坑实证（29K 档假阳/非流式口径 +0.8s/chunk 边界溢出
  # 21tok 断崖/decode-encode 回缩 8192→6240）——任何"复刻"都会引入口径漂移；
  # 锚（V4B 4992 与事故带 2210-2821）都是这套采集器量的，同 harness 才可比。
  # 自动分诊第一层保留：canary 载荷窗内四机并行采样 SM 时钟，楔死机直接点名。
  for _mh in $_WORKERS; do
    ssh "$_mh" 'rm -f /tmp/gate-clkwatch.log; for i in 1 2 3 4 5; do nvidia-smi --query-gpu=utilization.gpu,clocks.sm --format=csv,noheader,nounits; sleep 3; done > /tmp/gate-clkwatch.log 2>&1' &
  done
  ( for i in 1 2 3 4 5; do nvidia-smi --query-gpu=utilization.gpu,clocks.sm --format=csv,noheader,nounits; sleep 3; done > /tmp/gate-clkwatch-01.log ) &
  _b4=$(ls -t "$HOME/dsv41-flash-dgxsparks/state/bench-results" | head -1)
  # 审计 P2 修：无超时的 exec 在引擎死锁时门禁整体挂死——900s 上限后走红（采集器
  # 正常路径 ~40s，900s=超时即故障证据）
  timeout 900 docker exec -e PREFILL_SIZES=8192 -e CONCURRENCIES=1 dsv41-head \
    python3 /state/prv3_collector.py > /tmp/gate-canary-prv3.log 2>&1
  _canary_rc=$?
  wait  # 审计 P3 修：等齐四个时钟采样作业（15s 窗）再收数——旧 sleep 4 只收到部分窗
  # 自动分诊第一层：载荷窗内哪台机器 util≥50% 而 clock<1200MHz，直接点名
  _tri=""
  for _mh in $_HEAD_H $_WORKERS; do
    if [ "$_mh" = "$_HEAD_H" ]; then
      _w=$(cat /tmp/gate-clkwatch-01.log 2>/dev/null)
    else
      _w=$(ssh "$_mh" 'cat /tmp/gate-clkwatch.log 2>/dev/null' 2>/dev/null)
    fi
    _slow=$(printf '%s\n' "$_w" | awk -F'[, ]+' '$1>=50 && $2<1200 {print $2"MHz@"$1"pct"; exit}')
    [ -n "$_slow" ] && _tri="$_tri $_mh=${_slow}"
  done
  _d=$(ls -t "$HOME/dsv41-flash-dgxsparks/state/bench-results" | head -1)
  _cj="$HOME/dsv41-flash-dgxsparks/state/bench-results/$_d/8192-c1-w0.json"
  # 一次解析出 t/s 与 tok/wall；防假阳：要求采集器真生成了新目录（失败时 ls -t
  # 会捡到旧目录的陈旧绿数据，$_b4 前后对比堵死）
  _out=$(python3 -c "
import json
st=json.load(open('$_cj'))
tot=sum(x.get('prompt_tokens',0) for x in st)
t0=min(x['t0'] for x in st); te=max(x['t_end'] for x in st)
print(int(tot/(te-t0)) if te>t0 else 0, int(tot), round(te-t0,3))" 2>/dev/null)
  _tps=${_out%% *}; _rest=${_out#* }; _pt=${_rest%% *}
  if [[ "$_canary_rc" = 0 && "$_d" != "$_b4" && -n "${_tps:-}" && "$_tps" =~ ^[0-9]+$ && "$_tps" -ge 4500 ]]; then
    ok "perf canary：PRv3 8192-c1 = ${_tps} t/s ≥4500（${_pt} tok；分诊树未触发${_tri:+但载荷窗时钟异常:$_tri}）"
  elif [[ "$_d" = "$_b4" || -z "${_tps:-}" || "$_tps" = 0 ]]; then
    bad "perf canary 执行失败（rc=$_canary_rc；新结果目录未生成或解析失败，明细 /tmp/gate-canary-prv3.log 与 state/bench-results/）"
  else
    bad "perf canary：PRv3 8192-c1 = ${_tps} t/s <4500（prefill 回归嫌疑）→ 分诊：${_tri:+①时钟楔死实锤[$_tri ]=关机拔墙上AC冷断电（warm reboot 无效；runbook §7）；}②无楔死则 fabric（bash ~/w6-kit/s4_bench.sh timed，1MB/32MB 对照 A0 6.28/14.31）→ ③autotune golden（上方检查项）→ ④~/w6-kit/guard/guardctl.sh doctor"
  fi
fi

# ── 汇总 ──────────────────────────────────────────────────────────────────
echo
if [[ "$JSON" -eq 1 ]]; then
  printf '{"pass":%d,"fail":%d,"full":%s,"results":[' "$pass" "$fail" "$([[ $FULL -eq 1 ]] && echo true || echo false)"
  for i in "${!results[@]}"; do
    [[ $i -gt 0 ]] && printf ','
    printf '"%s"' "${results[$i]}"
  done
  printf ']}\n'
fi
if [[ "$fail" -eq 0 ]]; then
  echo "[+] GATE PASSED（$pass 项）—— 引擎可信"
  exit 0
else
  echo "[x] GATE FAILED（$pass 过 / $fail 败）—— 不要交付"
  exit 1
fi
