#!/usr/bin/env bash
# 在目标集群计算节点运行一次最小能力探针，输出 PROBE_ 开头的解析结果。
#
# 用法：
#   ./run-compute-probe.sh [--cluster <集群短名>] [--cpus 4] [--time 00:10:00] [--accelerators 1]

set -euo pipefail

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

parse_cluster_arg "$@"
set -- "${REST[@]+${REST[@]}}"

CPUS=4
TIME=00:10:00
ACCEL=1
REMOTE_USER=""
PYTHON_BIN=""

while [ $# -gt 0 ]; do
    case "$1" in
        --cpus) CPUS="${2:-$CPUS}"; shift 2 ;;
        --cpus=*) CPUS="${1#*=}"; shift ;;
        --time) TIME="${2:-$TIME}"; shift 2 ;;
        --time=*) TIME="${1#*=}"; shift ;;
        --accelerators) ACCEL="${2:-$ACCEL}"; shift 2 ;;
        --accelerators=*) ACCEL="${1#*=}"; shift ;;
        --user) REMOTE_USER="${2:-}"; shift 2 ;;
        --user=*) REMOTE_USER="${1#*=}"; shift ;;
        --python) PYTHON_BIN="${2:-}"; shift 2 ;;
        --python=*) PYTHON_BIN="${1#*=}"; shift ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) die "未知参数: $1" ;;
    esac
done

[ -n "${CLUSTER:-}" ] || die "请用 --cluster <集群短名> 指定集群。"
load_cluster "$CLUSTER"

[ "${SCHEDULER:-slurm}" = "slurm" ] || die "${CLUSTER_ID} 不是 Slurm 调度器，暂不支持自动计算节点探针。"
[ -n "${PARTITION:-}" ] || die "${CLUSTER_ID} 的 PARTITION 为空，无法提交计算节点探针。"

REMOTE_USER="${REMOTE_USER:-${REMOTE_USER_DETECTED:-$(whoami)}}"
HOME_DIR="${HOME_BASE}/${REMOTE_USER}"
PROBE_BASE="${HOME_DIR}/scnet-hpc-probe"

ssh_cmd() { ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 "$@"; }
scp_cmd() { scp -o BatchMode=yes -o ConnectTimeout=20 "$@"; }

PYTHON_MODULE_LINE=""
if [ -z "${PYTHON_MODULE:-}" ]; then
    PYTHON_MODULE_DETECTED="$(ssh_cmd "$CLUSTER_ID" "bash -lc 'module avail 2>&1'" 2>/dev/null \
        | awk '/^(python|apps\/python)\/3\./{print $1; exit}')"
    [ -n "$PYTHON_MODULE_DETECTED" ] && PYTHON_MODULE="$PYTHON_MODULE_DETECTED"
fi
[ -n "${PYTHON_MODULE:-}" ] && PYTHON_MODULE_LINE="module load ${PYTHON_MODULE}"

MEM_LINE=""
if [ -n "${DEF_MEM_PER_CPU:-}" ]; then
    MEM_MB=$(( CPUS * DEF_MEM_PER_CPU ))
    MEM_GB=$(( MEM_MB / 1024 ))
    [ "$MEM_GB" -gt 1 ] && MEM_GB=$(( MEM_GB - 1 ))
    MEM_LINE="#SBATCH --mem=${MEM_GB}gb"
fi

GRES_LINE=""
if [ -n "${GRES_TYPE:-}" ]; then
    GRES_LINE="#SBATCH --gres=${GRES_TYPE}:${ACCEL}"
fi

MODULE_LINE=""
[ -n "${MODULE_LOADS:-}" ] && MODULE_LINE="module load ${MODULE_LOADS}"

VENV_LINE=""
[ -n "${DEFAULT_VENV:-}" ] && VENV_LINE="source ${HOME_DIR}/${DEFAULT_VENV}/bin/activate"

TMPDIR_LOCAL=$(mktemp -d)
trap 'rm -rf "$TMPDIR_LOCAL"' EXIT
cp "$REPO_ROOT/scripts/compute-probe.py" "$TMPDIR_LOCAL/compute-probe.py"

cat > "$TMPDIR_LOCAL/probe.slurm" <<EOF
#!/bin/bash -l
#SBATCH --job-name=scnet_hpc_probe
#SBATCH --partition=${PARTITION}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=${CPUS}
${GRES_LINE}
${MEM_LINE}
#SBATCH --time=${TIME}
#SBATCH --output=${HOME_DIR}/scripts/logs/scnet-hpc-probe_%j.out
#SBATCH --error=${HOME_DIR}/scripts/logs/scnet-hpc-probe_%j.err

module purge
${MODULE_LINE}
${PYTHON_MODULE_LINE}
${VENV_LINE}
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# 部分集群 module purge 后没有 python3 这个命令，按候选名兜底找 Python。
PYTHON_BIN="${PYTHON_BIN}"
if [ -z "\$PYTHON_BIN" ]; then
    for candidate in python3 python3.8 python3.9 python3.10 python3.11; do
        if command -v "\$candidate" >/dev/null 2>&1; then
            PYTHON_BIN="\$candidate"
            break
        fi
    done
fi
[ -n "\$PYTHON_BIN" ] || { echo "PYTHON_NOT_FOUND" >&2; exit 127; }
"\$PYTHON_BIN" ${PROBE_BASE}.py
rc=\$?
echo "PROBE_EXIT=\$rc"
exit \$rc
EOF

ssh_cmd "$CLUSTER_ID" "mkdir -p ${HOME_DIR}/scripts/logs"
scp_cmd -q "$TMPDIR_LOCAL/compute-probe.py" "${CLUSTER_ID}:${PROBE_BASE}.py"
scp_cmd -q "$TMPDIR_LOCAL/probe.slurm" "${CLUSTER_ID}:${PROBE_BASE}.slurm"

JOBID=$(ssh_cmd "$CLUSTER_ID" "cd ${HOME_DIR} && sbatch --parsable --wait ${PROBE_BASE}.slurm" | tail -1)
OUT=$(ssh_cmd "$CLUSTER_ID" "cat ${HOME_DIR}/scripts/logs/scnet-hpc-probe_${JOBID}.out" 2>/dev/null || true)
ERR=$(ssh_cmd "$CLUSTER_ID" "cat ${HOME_DIR}/scripts/logs/scnet-hpc-probe_${JOBID}.err" 2>/dev/null || true)

if [ -n "$OUT" ]; then
    printf '%s\n' "$OUT"
else
    printf '%s\n' "$ERR" >&2
fi

ssh_cmd "$CLUSTER_ID" "rm -f ${PROBE_BASE}.py ${PROBE_BASE}.slurm ${HOME_DIR}/scripts/logs/scnet-hpc-probe_${JOBID}.out ${HOME_DIR}/scripts/logs/scnet-hpc-probe_${JOBID}.err"
