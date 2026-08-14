#!/usr/bin/env bash
# 加载集群 profile。被其他脚本 source。
#
#   . "$(dirname "$0")/_common.sh"
#   load_cluster "$CLUSTER"        # 空则自动选择
#
# 自动选择规则：clusters/ 下只有一个非模板 profile 时用它，否则要求显式指定。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_DIR="$REPO_ROOT/clusters"

die() { printf '错误: %s\n' "$1" >&2; exit 1; }
info() { printf '  %s\n' "$1"; }

list_clusters() {
    find "$CLUSTER_DIR" -maxdepth 1 -name '*.conf' ! -name '_*' -exec basename {} .conf \; 2>/dev/null | sort
}

load_cluster() {
    local want="${1:-}"
    local available
    available=$(list_clusters)

    [ -n "$available" ] || die "clusters/ 下没有可用的 profile。
从模板新建一个：
  cp $CLUSTER_DIR/_template.conf $CLUSTER_DIR/<集群短名>.conf"

    if [ -z "$want" ]; then
        local count
        count=$(printf '%s\n' "$available" | grep -c .)
        if [ "$count" -eq 1 ]; then
            want="$available"
        else
            die "有多个集群 profile，请用 --cluster <名> 指定：
$(printf '%s\n' "$available" | sed 's/^/  /')"
        fi
    fi

    local conf="$CLUSTER_DIR/$want.conf"
    [ -f "$conf" ] || die "找不到 profile: $conf
可用的：
$(printf '%s\n' "$available" | sed 's/^/  /')"

    # shellcheck disable=SC1090
    . "$conf"

    [ -n "${CLUSTER_ID:-}" ] || die "$conf 里 CLUSTER_ID 为空"
    [ -n "${SSH_HOST:-}" ]   || die "$conf 里 SSH_HOST 为空"
    : "${SSH_PORT:=22}"
    : "${HOME_BASE:=/public/home}"

    CLUSTER_CONF="$conf"
}

# 从参数里摘出 --cluster <名>，剩下的放进 REST[]
parse_cluster_arg() {
    CLUSTER=""
    REST=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --cluster) CLUSTER="${2:-}"; shift 2 ;;
            --cluster=*) CLUSTER="${1#*=}"; shift ;;
            *) REST+=("$1"); shift ;;
        esac
    done
}
