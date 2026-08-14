#!/usr/bin/env bash
# 从 canonical scnet-hpc 仓库同步 skill 内容到本仓库的 skills/scnet-hpc/。
#
# 默认源：../skills/scnet-hpc（本地同目录）；也可用 --src <路径> 指定。
# 只同步 SKILL.md、clusters/、references/ 和 scripts/（排除 install.sh）。
# SKILL.md 会做 DSH 适配：去掉 Claude Code 专用的 install.sh 安装说明。

set -euo pipefail

SRC="${DSCNET_SRC:-../skills/scnet-hpc}"
while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC="${2:-}"; shift 2 ;;
    --src=*) SRC="${1#*=}"; shift ;;
    -h|--help) sed -n '2,6p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

DST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills/scnet-hpc"

[ -f "$SRC/SKILL.md" ] || { echo "错误: 源目录找不到 SKILL.md: $SRC" >&2; exit 1; }

mkdir -p "$DST"

# 生成 DSH 版 SKILL.md：删除 install.sh 表格行，替换「换机器」小节
awk '
  /^\| `scripts\/install\.sh` \|/ { next }
  /^## 换机器$/ {
    print
    print ""
    print "本插件已随 DeepSeek Harness 安装，换机器时用 `dsh plugin --profile web add` 重装即可。"
    print "配置集群连接："
    print ""
    print "```bash"
    print "./scripts/setup-ssh.sh <私钥文件>              # 配连接（自动读唯一的 profile）"
    print "```"
    in_replace = 1
    next
  }
  in_replace && /^## / { in_replace = 0 }
  in_replace { next }
  { print }
' "$SRC/SKILL.md" > "$DST/SKILL.md"

rm -rf "$DST/clusters" "$DST/references" "$DST/scripts"
cp -R "$SRC/clusters" "$DST/clusters"
cp -R "$SRC/references" "$DST/references"

mkdir -p "$DST/scripts"
for f in _common.sh new-job.sh setup-ssh.sh probe-cluster.sh; do
  [ -f "$SRC/scripts/$f" ] && cp "$SRC/scripts/$f" "$DST/scripts/$f"
done
chmod +x "$DST/scripts/"*.sh

echo "已同步：$SRC -> $DST"
find "$DST" -maxdepth 2 -print | sort
