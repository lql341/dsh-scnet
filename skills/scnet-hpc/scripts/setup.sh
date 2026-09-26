#!/usr/bin/env bash
# SCNet HPC first-use configuration panel.
#
# This is the dependency-light entrypoint for new machines. Advanced OpenAPI
# discovery remains available through: python3 scripts/scnet.py setup

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_common.sh"

BACKEND=""
CLUSTER=""
SKIP_CONNECT=no
SSH_KEY=""
SSH_USER=""

usage() {
    sed -n '2,8p' "$0" | sed 's/^# \?//'
    cat <<'EOF'

用法：
  ./scripts/setup.sh
  ./scripts/setup.sh --cluster <profile> --backend ssh
  ./scripts/setup.sh --skip-connect

backend 可选：ssh、openapi、both。默认进入交互配置面板。
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --cluster)
            [ $# -ge 2 ] || die "--cluster 缺少参数"
            CLUSTER="$2"
            shift 2
            ;;
        --cluster=*) CLUSTER="${1#*=}"; shift ;;
        --backend)
            [ $# -ge 2 ] || die "--backend 缺少参数"
            BACKEND="$2"
            shift 2
            ;;
        --backend=*) BACKEND="${1#*=}"; shift ;;
        --skip-connect) SKIP_CONNECT=yes; shift ;;
        --ssh-key)
            [ $# -ge 2 ] || die "--ssh-key 缺少参数"
            SSH_KEY="$2"
            shift 2
            ;;
        --ssh-key=*) SSH_KEY="${1#*=}"; shift ;;
        --username)
            [ $# -ge 2 ] || die "--username 缺少参数"
            SSH_USER="$2"
            shift 2
            ;;
        --username=*) SSH_USER="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "未知参数: $1" ;;
    esac
done

require_tty() {
    [ -t 0 ] || die "配置面板需要交互式终端；非交互部署请预先生成 config.json 或使用 Python/CI 专用流程"
}

ask() {
    local prompt="$1"
    local default="${2:-}"
    local answer
    if [ -n "$default" ]; then
        printf '%s [%s]: ' "$prompt" "$default" >&2
    else
        printf '%s: ' "$prompt" >&2
    fi
    IFS= read -r answer
    printf '%s' "${answer:-$default}"
}

yes_no() {
    local prompt="$1"
    local default="${2:-yes}"
    local hint="Y/n"
    [ "$default" = no ] && hint="y/N"
    local answer
    printf '%s [%s]: ' "$prompt" "$hint" >&2
    IFS= read -r answer
    answer=$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')
    [ -z "$answer" ] && [ "$default" = yes ] && return 0
    [ "$answer" = y ] || [ "$answer" = yes ]
}

choose() {
    local prompt="$1"
    shift
    local choices=("$@")
    local index choice
    printf '%s\n' "$prompt" >&2
    for index in "${!choices[@]}"; do
        printf '  %d. %s\n' "$((index + 1))" "${choices[$index]}" >&2
    done
    local selected
    selected=$(ask "选择" "1")
    [[ "$selected" =~ ^[0-9]+$ ]] || die "选择必须是数字"
    [ "$selected" -ge 1 ] && [ "$selected" -le "${#choices[@]}" ] \
        || die "选择超出范围"
    choice="${choices[$((selected - 1))]}"
    printf '%s' "$choice"
}

validate_scalar() {
    local name="$1"
    local value="$2"
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* && "$value" != *'"'* ]] \
        || die "$name 包含不安全字符"
}

validate_identifier() {
    local name="$1"
    local value="$2"
    [[ "$value" =~ ^[A-Za-z0-9._:-]+$ ]] || die "$name 包含不安全字符"
}

json_string() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    printf '"%s"' "$value"
}

write_config() {
    local config_root="${XDG_CONFIG_HOME:-$HOME/.config}/scnet-hpc"
    local config_path="$config_root/config.json"
    mkdir -p "$config_root"
    chmod 700 "$config_root"

    local temporary
    temporary=$(mktemp "$config_root/.config.XXXXXX")
    chmod 600 "$temporary"
    {
        printf '{\n  "version": 1,\n  "cluster": '
        json_string "$CLUSTER"
        printf ',\n  "default_backend": '
        json_string "$DEFAULT_BACKEND"
        if [ -n "$SSH_USER" ]; then
            printf ',\n  "ssh": {"username": '
            json_string "$SSH_USER"
            printf '}'
        fi
        if [ -n "$OPENAPI_REGION" ]; then
            printf ',\n  "openapi": {"region_id": '
            json_string "$OPENAPI_REGION"
            if [ -n "$OPENAPI_SCHEDULER" ]; then
                printf ', "scheduler_id": '
                json_string "$OPENAPI_SCHEDULER"
            fi
            if [ -n "$OPENAPI_USER" ]; then
                printf ', "username": '
                json_string "$OPENAPI_USER"
            fi
            printf '}'
        fi
        printf '\n}\n'
    } >"$temporary"
    mv "$temporary" "$config_path"
    printf '%s\n' "$config_path"
}

require_tty

printf '\nSCNet HPC 首次配置面板（Bash）\n' >&2
printf '================================\n' >&2
printf '此面板只保存非敏感选择；AK/SK/token 不会写入配置文件。\n\n' >&2

available=$(list_clusters)
[ -n "$available" ] || die "clusters/ 下没有 profile"
if [ -z "$CLUSTER" ]; then
    cluster_choices=()
    while IFS= read -r cluster_choice; do
        [ -n "$cluster_choice" ] && cluster_choices+=("$cluster_choice")
    done <<EOF
$available
EOF
    CLUSTER=$(choose "选择默认集群 profile：" "${cluster_choices[@]}")
fi
[[ "$CLUSTER" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
    || die "集群 profile 名称包含不安全字符"

if [ -z "$BACKEND" ]; then
    BACKEND=$(choose "选择默认 backend：" \
        "ssh（推荐，支持环境和深度诊断）" \
        "openapi（结构化控制面）" \
        "both（同时配置，默认使用 SSH）")
    case "$BACKEND" in
        ssh*) BACKEND=ssh ;;
        openapi*) BACKEND=openapi ;;
        both*) BACKEND=both ;;
    esac
fi
case "$BACKEND" in
    ssh|openapi|both) ;;
    *) die "backend 必须是 ssh、openapi 或 both" ;;
esac

if [ "$BACKEND" = ssh ] || [ "$BACKEND" = both ]; then
    load_cluster "$CLUSTER"
else
    profile_path="$CLUSTER_DIR/$CLUSTER.conf"
    [ -f "$profile_path" ] || die "找不到 profile: $profile_path"
    # shellcheck disable=SC1090
    . "$profile_path"
    [ "${CLUSTER_ID:-}" = "$CLUSTER" ] || die "$profile_path 的 CLUSTER_ID 不匹配"
fi

DEFAULT_BACKEND="$BACKEND"
if [ "$BACKEND" = both ]; then
    DEFAULT_BACKEND=$(choose "选择默认 backend：" "ssh" "openapi")
fi

OPENAPI_REGION=""
OPENAPI_SCHEDULER=""
OPENAPI_USER=""

if [ "$BACKEND" = ssh ] || [ "$BACKEND" = both ]; then
    SSH_USER="${SSH_USER:-$(ask "远端用户名")}"
    validate_identifier "远端用户名" "$SSH_USER"
    [ -n "$SSH_USER" ] || die "远端用户名不能为空"
    if [ "$SKIP_CONNECT" = no ]; then
        SSH_KEY="${SSH_KEY:-$(ask "私钥文件路径")}"
        SSH_KEY="${SSH_KEY/#\~/$HOME}"
        [ -f "$SSH_KEY" ] || die "找不到私钥文件: $SSH_KEY"
        "$SCRIPT_DIR/setup-ssh.sh" --cluster "$CLUSTER" "$SSH_KEY" "$SSH_USER"
    else
        printf '已跳过 SSH 私钥安装和连接测试。\n' >&2
    fi
fi

if [ "$BACKEND" = openapi ] || [ "$BACKEND" = both ]; then
    OPENAPI_REGION="${OPENAPI_REGION:-$(ask "OpenAPI 区域 ID")}"
    OPENAPI_SCHEDULER="${OPENAPI_SCHEDULER:-$(ask "调度器 ID（未知可留空）")}"
    OPENAPI_USER="${OPENAPI_USER:-$(ask "区域用户名（未知可留空）")}"
    validate_scalar "OpenAPI 区域 ID" "$OPENAPI_REGION"
    validate_scalar "OpenAPI 调度器 ID" "$OPENAPI_SCHEDULER"
    validate_identifier "OpenAPI 区域 ID" "$OPENAPI_REGION"
    [ -z "$OPENAPI_SCHEDULER" ] || validate_identifier "OpenAPI 调度器 ID" "$OPENAPI_SCHEDULER"
    [ -z "$OPENAPI_USER" ] || validate_identifier "OpenAPI 用户名" "$OPENAPI_USER"
    [ -n "$OPENAPI_REGION" ] || die "OpenAPI 区域 ID 不能为空"
    printf '%s\n' \
        "OpenAPI 选择已保存，但 Bash 面板不会验证凭据。" \
        "请通过环境变量或 Python 面板验证：" \
        "  python3 scripts/scnet.py --backend openapi doctor" >&2
fi

config_path=$(write_config)
printf '\n已保存配置：%s\n' "$config_path" >&2
printf '下一步：%s/scripts/scnet.py doctor\n' "$REPO_ROOT" >&2
