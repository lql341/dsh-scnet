#!/usr/bin/env bash
# SCNet HPC configuration and credential-rotation panel.
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
        printf '\n}\n'
    } >"$temporary"
    mv "$temporary" "$config_path"
    printf '%s\n' "$config_path"
}

write_ssh_profile() {
    [ -n "$SSH_USER" ] || return 0
    local config_root="${XDG_CONFIG_HOME:-$HOME/.config}/scnet-hpc"
    local ssh_root="$config_root/ssh"
    local profile_path="$ssh_root/$CLUSTER.json"
    local expiry=""
    local key_base=""
    local installed_key="$HOME/.ssh/id_rsa_$CLUSTER_ID"
    local fingerprint=""
    local updated_at=""
    local existing_key_path=""
    local existing_source=""
    local existing_expiry=""
    local existing_fingerprint=""
    local existing_updated=""
    mkdir -p "$ssh_root"
    chmod 700 "$ssh_root"
    existing_key_path=$(json_string_value "$profile_path" key_path)
    existing_source=$(json_string_value "$profile_path" key_source_name)
    existing_expiry=$(json_string_value "$profile_path" key_expires_at)
    existing_fingerprint=$(json_string_value "$profile_path" key_fingerprint)
    existing_updated=$(json_string_value "$profile_path" updated_at)
    if [ -n "$SSH_KEY" ]; then
        key_base=$(basename "$SSH_KEY")
        expiry=$(printf '%s' "$key_base" | sed -nE \
            's/.*RsaKeyExpireTime[_-]([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/p')
        updated_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
        if [ -f "$installed_key" ]; then
            fingerprint=$(ssh-keygen -lf "$installed_key" 2>/dev/null \
                | awk '{print $2; exit}')
        fi
    else
        installed_key="$existing_key_path"
        key_base="$existing_source"
        expiry="$existing_expiry"
        fingerprint="$existing_fingerprint"
        updated_at="$existing_updated"
    fi
    local temporary
    temporary=$(mktemp "$ssh_root/.$CLUSTER.XXXXXX")
    chmod 600 "$temporary"
    {
        printf '{\n  "username": '
        json_string "$SSH_USER"
        if [ -n "$installed_key" ]; then
            printf ',\n  "key_path": '
            json_string "$installed_key"
        fi
        if [ -n "$key_base" ]; then
            printf ',\n  "key_source_name": '
            json_string "$key_base"
        fi
        if [ -n "$updated_at" ]; then
            printf ',\n  "updated_at": '
            json_string "$updated_at"
        fi
        if [ -n "$expiry" ]; then
            printf ',\n  "key_expires_at": '
            json_string "$expiry"
        fi
        if [ -n "$fingerprint" ]; then
            printf ',\n  "key_fingerprint": '
            json_string "$fingerprint"
        fi
        printf '\n}\n'
    } >"$temporary"
    mv "$temporary" "$profile_path"
}

json_string_value() {
    local path="$1"
    local key="$2"
    [ -f "$path" ] || return 0
    sed -nE "s/.*\"${key}\"[[:space:]]*:[[:space:]]*\"([^\"]*)\".*/\\1/p" \
        "$path" | head -1
}

detect_ssh_user() {
    local key_path="${1:-}"
    local config_root="${XDG_CONFIG_HOME:-$HOME/.config}/scnet-hpc"
    local saved
    saved=$(json_string_value "$config_root/ssh/$CLUSTER.json" username)
    [ -n "$saved" ] && { printf '%s' "$saved"; return; }

    if [ -n "$key_path" ] && [ -n "${KEY_NAME_MARKER:-}" ] \
        && [[ "$KEY_NAME_MARKER" != *"<"* ]]; then
        local base
        base=$(basename "$key_path")
        case "$base" in
            *"$KEY_NAME_MARKER"*)
                printf '%s' "${base%%"$KEY_NAME_MARKER"*}"
                return
                ;;
        esac
    fi
    if [ -n "$key_path" ] && [ -n "${SSH_HOST:-}" ]; then
        local host_marker="_${SSH_HOST}_"
        local base
        base=$(basename "$key_path")
        case "$base" in
            *"$host_marker"*)
                printf '%s' "${base%%"$host_marker"*}"
                return
                ;;
        esac
    fi

    local resolved_host resolved_user
    resolved_host=$(ssh -G "$CLUSTER_ID" 2>/dev/null \
        | awk '/^hostname /{print $2; exit}')
    resolved_user=$(ssh -G "$CLUSTER_ID" 2>/dev/null \
        | awk '/^user /{print $2; exit}')
    if [ "$resolved_host" = "${SSH_HOST:-}" ]; then
        printf '%s' "$resolved_user"
    fi
}

require_tty

printf '\nSCNet HPC 配置/维护面板（Bash）\n' >&2
printf '==================================\n' >&2
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
    export SCNET_HPC_LIVE_NODE_COUNT=no
    load_cluster "$CLUSTER"
    unset SCNET_HPC_LIVE_NODE_COUNT
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

if [ "$BACKEND" = ssh ] || [ "$BACKEND" = both ]; then
    if [ "$SKIP_CONNECT" = no ]; then
        SSH_KEY="${SSH_KEY:-$(ask "私钥文件路径")}"
        SSH_KEY="${SSH_KEY/#\~/$HOME}"
        [ -f "$SSH_KEY" ] || die "找不到私钥文件: $SSH_KEY"
    fi
    detected_user=$(detect_ssh_user "$SSH_KEY")
    SSH_USER="${SSH_USER:-$(ask "远端用户名（已自动探测，可直接回车）" "$detected_user")}"
    validate_identifier "远端用户名" "$SSH_USER"
    [ -n "$SSH_USER" ] || die "无法自动探测 SSH 用户名，请手工输入"
    if [ "$SKIP_CONNECT" = no ]; then
        "$SCRIPT_DIR/setup-ssh.sh" --cluster "$CLUSTER" "$SSH_KEY" "$SSH_USER"
    else
        printf '已跳过 SSH 私钥安装和连接测试。\n' >&2
    fi
fi

if [ "$BACKEND" = openapi ] || [ "$BACKEND" = both ]; then
    if command -v python3 >/dev/null 2>&1; then
        printf '%s\n' \
            "OpenAPI 使用一组平台 AK/SK 自动发现全部授权区域。" >&2
        python3 "$SCRIPT_DIR/scnet.py" setup --mode openapi
    else
        printf '%s\n' \
            "OpenAPI backend 需要 Python 3；SSH 配置不受影响。" \
            "安装 Python 3 后运行：python3 scripts/scnet.py setup --mode openapi" >&2
    fi
fi

write_ssh_profile
config_path=$(write_config)
printf '\n已保存配置：%s\n' "$config_path" >&2
printf '下一步：%s/scripts/scnet.py doctor\n' "$REPO_ROOT" >&2
