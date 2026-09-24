#!/usr/bin/env bash
# stop.sh — tear down DeepSeek-V4.1-Flash SGLang.
#
# Both profiles are covered (see start.sh's "Profiles:" block): this reads
# ENV_FILE and defaults the same way start.sh does — .env.tp4 when present
# (4 Sparks, TP4, the profile this repository ships), else .env (the legacy
# 3-Spark dev triangle). The "spark1/spark2/spark3" wording below is that
# legacy description; spark1 is its name for the head node.
#
# Stops:
#   - dsv41-head on the head node (spark1) — rank 0 + API :8888
#   - dsv41-worker on the workers (spark2/spark3)
#   - log-tail helper
#   - leftover sglang.launch_server in those containers
#
# Keeps:
#   - checkpoint on the head node
#   - the container image (its name is printed at the end; it comes from ENV_FILE)
#   - shared NFSv4 exporter (vllm-fn-nfs) — Qwen/GLM still use it
#   - docker volume dsv41-weights unless you pass --unmount
#
# Usage:
#   ./stop.sh              stop serve on every node named in ENV_FILE
#   ./stop.sh --unmount    also drop worker NFS volumes (weights stay on the head)
#   ./start.sh stop        same
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

UNMOUNT="${UNMOUNT:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --unmount|-u) UNMOUNT=1 ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "unknown arg: $1 (try ./stop.sh --help)" >&2
      exit 1
      ;;
  esac
  shift
done

# 2026-09-21 事故教训：默认 source 旧双机 .env（10.0.0.2/3 + zurih@spark2/3）⇒
# 对现四机 TP4 集群（.env.tp4 的 WORKER_IPS 三台）worker 清理**静默空转**
# （systemd ExecStop 不带 ENV_FILE 时必踩）。生产形态=.env.tp4 存在则优先。
if [[ -z "${ENV_FILE:-}" ]]; then
  if [[ -f "$ROOT/.env.tp4" ]]; then ENV_FILE="$ROOT/.env.tp4"
  else ENV_FILE="$ROOT/.env"; fi
fi
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ENV_FILE"
  set +a
fi

_abs() { readlink -f "$1" 2>/dev/null || echo "$1"; }

HEAD_CTN="${HEAD_CTN:-dsv41-head}"
WORKER_CTN="${WORKER_CTN:-dsv41-worker}"
PORT="${PORT:-8888}"
_list() { tr ',' ' ' <<<"$1"; }
if [[ -n "${WORKER_IPS:-}" ]]; then
  read -r -a WORKER_IPS <<<"$(_list "$WORKER_IPS")"
else
  WORKER_IPS=("${WORKER1_IP:-10.0.0.2}" "${WORKER2_IP:-10.0.0.3}")
fi
if [[ -n "${WORKER_HOSTS:-}" ]]; then
  read -r -a WORKER_HOSTS <<<"$(_list "$WORKER_HOSTS")"
else
  WORKER_HOSTS=()
  for _i in "${!WORKER_IPS[@]}"; do
    _v="WORKER$((_i + 1))_HOST"
    WORKER_HOSTS+=("${!_v:-${WORKER_IPS[$_i]}}")
  done
fi
# 2026-09-21：zurih 是旧双机集群账号；现集群 worker 同为当前用户，随 .env.tp4 走
WORKER_USER="${WORKER_USER:-$USER}"
SSH_IDENTITY="$(_abs "${SSH_IDENTITY:-$HOME/.ssh/id_ed25519_shared}")"
NFS_VOLUME="${NFS_VOLUME:-dsv41-weights}"
# 这个变量**只用于收尾打印**（文件末尾的 "kept:" 一行），不参与任何删除动作。
# 所以这里不猜默认值：旧的 dsv41-3x-spark:local 属于 09-13 命名法，打印出来只会
# 让人照它去 docker images 里找一个根本不存在的镜像。正常路径下 ENV_FILE
# （默认 .env.tp4）已经给出真值；没有 env 时按「未 pin」如实说，不编。
IMAGE="${IMAGE:-}"
REMOTE_PY="${REMOTE_PY:-$ROOT/scripts/remote.py}"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
RM_TIMEOUT="${RM_TIMEOUT:-30}"

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'; NC=$'\033[0m'
info() { echo "${GREEN}[+]${NC} $*"; }
warn() { echo "${YELLOW}[!]${NC} $*"; }
err()  { echo "${RED}[x]${NC} $*" >&2; }

remote_on() {
  local host="$1"; shift
  local env_args=()
  [[ -f "$ENV_FILE" ]] && env_args=(--env-file "$ENV_FILE")
  python3 "$REMOTE_PY" "${env_args[@]}" \
    --host "$host" --user "$WORKER_USER" \
    --identity "$SSH_IDENTITY" \
    --timeout "${REMOTE_TIMEOUT:-60}" \
    "bash -lc $(printf '%q' "$*")"
}

_rm_ctn() {
  local name="$1"
  timeout "$RM_TIMEOUT" docker rm -f "$name" >/dev/null 2>&1 || true
}

_stop_sglang_in() {
  local ctn="$1"
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$ctn" || return 0
  docker exec "$ctn" bash -lc '
    pkill -TERM -f "[s]glang.launch_server" >/dev/null 2>&1 || true
    pkill -TERM -f "[s]glang.srt" >/dev/null 2>&1 || true
    sleep 1
    pkill -KILL -f "[s]glang.launch_server" >/dev/null 2>&1 || true
  ' 2>/dev/null || true
}

info "=== stop DeepSeek-V4.1-Flash (3× Spark SGLang) ==="

if [[ -f "$LOG_DIR/logtail.pid" ]]; then
  kill "$(cat "$LOG_DIR/logtail.pid")" 2>/dev/null || true
  rm -f "$LOG_DIR/logtail.pid"
fi
pkill -f "docker logs -f ${HEAD_CTN}" >/dev/null 2>&1 || true

info "head: SIGTERM sglang in $HEAD_CTN, then remove"
_stop_sglang_in "$HEAD_CTN"
_rm_ctn "$HEAD_CTN"
# anything else this recipe named
ids=$(docker ps -aq --filter "name=dsv41-" 2>/dev/null || true)
if [[ -n "$ids" ]]; then
  # shellcheck disable=SC2086
  timeout "$RM_TIMEOUT" docker rm -f $ids >/dev/null 2>&1 || true
fi

for h in "${WORKER_HOSTS[@]}"; do
  info "worker $WORKER_USER@$h: stop $WORKER_CTN"
  if remote_on "$h" "
    if docker ps --format '{{.Names}}' | grep -qx $(printf '%q' "$WORKER_CTN"); then
      docker exec $(printf '%q' "$WORKER_CTN") bash -lc '
        pkill -TERM -f \"[s]glang.launch_server\" >/dev/null 2>&1 || true
        sleep 1
        pkill -KILL -f \"[s]glang.launch_server\" >/dev/null 2>&1 || true
      ' 2>/dev/null || true
    fi
    timeout ${RM_TIMEOUT} docker rm -f $(printf '%q' "$WORKER_CTN") >/dev/null 2>&1 || docker rm -f $(printf '%q' "$WORKER_CTN") >/dev/null 2>&1 || true
    ids=\$(docker ps -aq --filter name=dsv41- 2>/dev/null || true)
    [ -n \"\$ids\" ] && docker rm -f \$ids >/dev/null 2>&1 || true
    echo STOPPED_$h
  " 2>/dev/null | grep -q "STOPPED_$h"; then
    info "  $h: container gone"
  else
    warn "  $h: SSH/docker cleanup failed (node unreachable?). GPU there may still be busy."
  fi
  if [[ "$UNMOUNT" == "1" ]]; then
    info "  $h: drop NFS volume $NFS_VOLUME"
    remote_on "$h" "docker volume rm $(printf '%q' "$NFS_VOLUME") >/dev/null 2>&1 || true" || true
  fi
done

echo
# 2026-09-21 防静默：逐台复核 worker 容器真的没了。拓扑失配/ssh 失败时上面只
# warn 一句就退（rc=0）——下游以为停干净了，下一靴 start 撞半死栈。残留 ⇒
# exit 2 + 打印手动修复命令，宁可红脸。
_failed_workers=()
for h in "${WORKER_HOSTS[@]}"; do
  # 审计 P1 修：赋值语句吃掉 remote_on 的 rc——worker 不可达时 _left 为空不入
  # failed、打印 workers all clean（GPU 仍被占、systemd rc=0 收场）。ssh 失败本身
  # 就是「未证实停干净」，按残留同级处理。
  if ! _left="$(remote_on "$h" 'docker ps -a --format "{{.Names}}" | grep -E "^dsv41-" | tr "\n" " "' 2>/dev/null)"; then
    _failed_workers+=("$h(ssh-fail:未证实停净)")
    continue
  fi
  if [[ -n "$_left" ]]; then
    _failed_workers+=("$h($_left)")
  fi
done
if [[ "${#_failed_workers[@]}" -gt 0 ]]; then
  err "worker 容器残留（stop 拓扑失配或 ssh 失败），手动修复后重跑："
  for _f in "${_failed_workers[@]}"; do
    err "  ssh ${_f%%(*} 'docker rm -f \$(docker ps -aq --filter name=dsv41-)'   # 残留: ${_f#*(}"
  done
  exit 2
else
  info "workers all clean: ${WORKER_HOSTS[*]}"
fi

if curl -sf --max-time 2 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1 \
   || curl -sf --max-time 2 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  warn "something is still answering on :${PORT}"
else
  info "API down on :${PORT}"
fi

left=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^dsv41-' || true)
if [[ -n "$left" ]]; then
  warn "still running on head: $left"
else
  info "no dsv41-* containers on head"
fi

info "kept: head-node weights, ${IMAGE:-<unpinned: no ENV_FILE loaded>} overlay, vllm-fn-nfs exporter"
[[ "$UNMOUNT" == "1" ]] || info "worker NFS volume $NFS_VOLUME kept (./stop.sh --unmount to drop it)"
info "start again with: ENV_FILE=.env.tp4 ./start.sh serve   # 生产形态必须带 ENV_FILE"
