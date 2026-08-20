#!/usr/bin/env bash
# 从 canonical scnet-hpc 仓库同步 skill 内容到本仓库的 skills/scnet-hpc/。
#
# 默认源：../../skills/scnet-hpc（当前 agent 目录布局）；也可用 --src <路径> 指定。
# 只同步 SKILL.md、clusters/、references/ 和 scripts/（排除 install.sh 和
# clusters/.cache 动态缓存，缓存属于本机运行结果，不应打进发布包）。
# SKILL.md 会做 DSH bundle 适配：排除 canonical 仓库专用的 install.sh 入口。

set -euo pipefail

SRC="${DSCNET_SRC:-../../skills/scnet-hpc}"
while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC="${2:-}"; shift 2 ;;
    --src=*) SRC="${1#*=}"; shift ;;
    -h|--help) sed -n '2,6p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

DST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills/scnet-hpc"

SRC="$(cd "$SRC" 2>/dev/null && pwd)" || { echo "错误: 源目录不存在: $SRC" >&2; exit 1; }
[ -f "$SRC/SKILL.md" ] || { echo "错误: 源目录找不到 SKILL.md: $SRC" >&2; exit 1; }
for required in clusters references scripts; do
  [ -d "$SRC/$required" ] || { echo "错误: 源目录缺少 $required/: $SRC" >&2; exit 1; }
done

mkdir -p "$DST"

# Generate the DSH copy without the canonical repository installer.
awk '!/^\| `scripts\/install\.sh` \|/' "$SRC/SKILL.md" > "$DST/SKILL.md"
rm -rf "$DST/clusters" "$DST/references" "$DST/scripts"
cp -R "$SRC/clusters" "$DST/clusters"
rm -rf "$DST/clusters/.cache"
cp -R "$SRC/references" "$DST/references"

mkdir -p "$DST/scripts"
for f in _common.sh new-job.sh setup-ssh.sh probe-cluster.sh refresh-cluster.sh run-compute-probe.sh compute-probe.py; do
  [ -f "$SRC/scripts/$f" ] && cp "$SRC/scripts/$f" "$DST/scripts/$f"
done
chmod +x "$DST/scripts/"*.sh

echo "已同步：$SRC -> $DST"
find "$DST" -maxdepth 2 -print | sort
