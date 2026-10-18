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
ACTION=""
SKIP_CONNECT=no
SSH_KEY=""
SSH_USER=""

usage() {
    sed -n '2,8p' "$0" | sed 's/^# \?//'
    cat <<'EOF'

用法：
  ./scripts/setup.sh
  ./scripts/setup.sh new|modify|status|reset
  ./scripts/setup.sh --cluster <profile> --backend ssh
  ./scripts/setup.sh --skip-connect

action 可选：new、modify、status、reset。
backend 可选：ssh、openapi、both。无参数时进入交互管理面板。
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
        new|modify|status|reset)
            [ -z "$ACTION" ] || die "只能指定一个 action"
            ACTION="$1"
            shift
            ;;
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
    local default_index="${SCNET_SETUP_CHOICE_DEFAULT:-1}"
    [[ "$default_index" =~ ^[0-9]+$ ]] || die "默认选项必须是数字"
    [ "$default_index" -ge 1 ] && [ "$default_index" -le "${#choices[@]}" ] || die "默认选项超出范围"
    if [ -t 0 ] && [ -t 2 ] && [ "${TERM:-dumb}" != "dumb" ]; then
        local selected=$((default_index - 1))
        local number=""
        local key sequence value
        local line_count=$(( ${#choices[@]} + 1 ))
        printf '%s\n' "$prompt" >&2
        printf '使用 ↑/↓ 移动，Enter 确认；也可输入编号后按 Enter；q 取消。\n' >&2

        render_choices() {
            local first="${1:-no}"
            local render_index pointer typed
            if [ "$first" != yes ]; then
                printf '\033[%dA' "$line_count" >&2
            fi
            for render_index in "${!choices[@]}"; do
                pointer=" "
                [ "$render_index" -eq "$selected" ] && pointer="▶"
                printf '\r\033[2K  %s %d. %s\n' \
                    "$pointer" "$((render_index + 1))" \
                    "${choices[$render_index]}" >&2
            done
            typed="编号：（可直接按 Enter）"
            [ -n "$number" ] && typed="编号：$number"
            printf '\r\033[2K  %s\n' "$typed" >&2
        }

        render_choices yes
        while true; do
            IFS= read -rsn1 key
            case "$key" in
                "")
                    if [ -n "$number" ]; then
                        value=$((10#$number))
                        if [ "$value" -ge 1 ] \
                            && [ "$value" -le "${#choices[@]}" ]; then
                            selected=$((value - 1))
                            break
                        fi
                        number=""
                        render_choices
                    else
                        break
                    fi
                    ;;
                $'\033')
                    sequence=""
                    IFS= read -rsn2 -t 1 sequence || true
                    case "$sequence" in
                        "[A") selected=$(( (selected - 1 + ${#choices[@]}) % ${#choices[@]} )); number=""; render_choices ;;
                        "[B") selected=$(( (selected + 1) % ${#choices[@]} )); number=""; render_choices ;;
                    esac
                    ;;
                q|Q) die "用户取消配置" ;;
                $'\177')
                    number="${number%?}"
                    render_choices
                    ;;
                [0-9])
                    number="${number}${key}"
                    render_choices
                    ;;
            esac
        done
        printf '已选择：%d. %s\n' \
            "$((selected + 1))" "${choices[$selected]}" >&2
        printf '%s' "${choices[$selected]}"
        return
    fi

    printf '%s\n' "$prompt" >&2
    for index in "${!choices[@]}"; do
        printf '  %d. %s\n' "$((index + 1))" "${choices[$index]}" >&2
    done
    printf '请输入 1-%d 的数字并按 Enter；直接按 Enter 使用默认项 %d。\n' \
        "${#choices[@]}" "$default_index" >&2
    printf '当前终端不支持交互导航，已使用数字输入模式。\n' >&2
    local selected
    selected=$(ask "选择" "$default_index")
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
    if [ -n "${PYTHON_BIN:-}" ]; then
        "$PYTHON_BIN" - "$SCRIPT_DIR" "$CLUSTER" "$DEFAULT_BACKEND" <<'PYCONFIG'
import sys
sys.path.insert(0, sys.argv[1])
from scnet_config import load_user_config, save_user_config
config = load_user_config()
config.update(version=1, cluster=sys.argv[2], default_backend=sys.argv[3])
print(save_user_config(config))
PYCONFIG
        return
    fi
    [ ! -f "$config_path" ] || die "更新已有主配置需要 Python 3，以保留其他配置字段"
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
case "$(uname -s)" in
    Darwin)
        printf '%s\n' \
            "macOS：在 Terminal 或 iTerm2 中使用 ↑/↓ 和 Enter，也可输入编号；Ctrl+C 可取消。" \
            "敏感输入不会回显；OpenAPI 凭据可保存到 macOS Keychain。" >&2
        ;;
    Linux)
        if [ -r /etc/os-release ] \
            && grep -Eq '^ID=(ubuntu|debian)$' /etc/os-release; then
            printf '%s\n' \
                "Ubuntu/Debian：在 Terminal 中使用 ↑/↓ 和 Enter，也可输入编号；Ctrl+C 可取消。" \
                "本机安全保存 AK/SK 可安装 libsecret-tools（sudo apt install libsecret-tools）；使用环境变量时无需安装。" >&2
        else
            printf '%s\n' "Linux：使用 ↑/↓ 和 Enter，也可输入编号；Ctrl+C 可取消。" >&2
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        printf '%s\n' \
            "Windows：OpenAPI 可在 PowerShell 中运行 python scripts/scnet.py setup，并使用系统凭据管理器。" \
            "SSH 自动安装请在 WSL2 内运行；WSL2 与 Windows OpenSSH 的私钥目录互相独立。" >&2
        ;;
esac
printf '\n' >&2

config_root="${XDG_CONFIG_HOME:-$HOME/.config}/scnet-hpc"
PYTHON_BIN="$(resolve_python)" || PYTHON_BIN=""
saved_backend=$(json_string_value "$config_root/config.json" default_backend)
action_default=2
if [ -n "$PYTHON_BIN" ]; then
    action_default=$("$PYTHON_BIN" - "$SCRIPT_DIR" <<'PYDEFAULT'
import sys
sys.path.insert(0, sys.argv[1])
from scnet_config import load_user_config
from scnet import _has_configuration
print(3 if _has_configuration(load_user_config()) else 2)
PYDEFAULT
    )
elif [ -f "$config_root/config.json" ] || [ -f "$config_root/openapi.json" ] \
    || compgen -G "$config_root/ssh/*.json" >/dev/null; then
    action_default=3
fi
if [ -z "$ACTION" ]; then
    action_label=$(SCNET_SETUP_CHOICE_DEFAULT="$action_default" choose "选择配置操作：" \
        "查看当前状态（status）" \
        "新增连接（new）" \
        "修改现有配置（modify）" \
        "重置配置（reset）")
    case "$action_label" in
        *status*) ACTION=status ;;
        *new*) ACTION=new ;;
        *modify*) ACTION=modify ;;
        *reset*) ACTION=reset ;;
    esac
fi

if [ "$ACTION" = status ] || [ "$ACTION" = reset ]; then
    if PYTHON_BIN="$(resolve_python)"; then
        exec "$PYTHON_BIN" "$SCRIPT_DIR/scnet.py" setup "$ACTION"
    fi
    [ "$ACTION" = status ] || die "reset 需要 Python 3 以执行安全的分范围重置"
    config_root="${XDG_CONFIG_HOME:-$HOME/.config}/scnet-hpc"
    printf '配置目录：%s\n' "$config_root"
    find "$config_root" -maxdepth 2 -type f -print 2>/dev/null || true
    exit 0
fi

if [ -z "$BACKEND" ]; then
    backend_default=1
    [ "$saved_backend" != ssh ] || backend_default=2
    BACKEND=$(SCNET_SETUP_CHOICE_DEFAULT="$backend_default" choose "选择要管理的 backend：" \
        "openapi（推荐：平台级 AK/SK 和多区域）" \
        "ssh（区域级用户名和私钥）" \
        "both（同时管理）")
    case "$BACKEND" in
        openapi*) BACKEND=openapi ;;
        ssh*) BACKEND=ssh ;;
        both*) BACKEND=both ;;
    esac
fi
case "$BACKEND" in
    ssh|openapi|both) ;;
    *) die "backend 必须是 ssh、openapi 或 both" ;;
esac

# Check requirements before installing keys or changing local configuration.
if [ "$BACKEND" = openapi ] || [ "$BACKEND" = both ]; then
    [ -n "$PYTHON_BIN" ] || die "OpenAPI 配置需要 Python 3；请设置 DSH_SCNET_PYTHON 或 SCNET_PYTHON，或安装 python3"
fi
if [ "$BACKEND" = ssh ] || [ "$BACKEND" = both ]; then
    [ -n "$PYTHON_BIN" ] || [ ! -f "$config_root/config.json" ] \
        || die "更新已有主配置需要 Python 3，以保留其他配置字段"
    available=$(list_clusters)
    [ -n "$available" ] || die "clusters/ 下没有 profile"
fi

if { [ "$BACKEND" = ssh ] || [ "$BACKEND" = both ]; } \
    && [ -z "$CLUSTER" ]; then
    cluster_choices=()
    while IFS= read -r cluster_choice; do
        [ -n "$cluster_choice" ] || continue
        metadata="${XDG_CONFIG_HOME:-$HOME/.config}/scnet-hpc/ssh/$cluster_choice.json"
        if [ "$ACTION" = new ] && [ ! -f "$metadata" ]; then
            cluster_choices+=("$cluster_choice")
        elif [ "$ACTION" = modify ] && [ -f "$metadata" ]; then
            cluster_choices+=("$cluster_choice")
        fi
    done <<EOF
$available
EOF
    [ "${#cluster_choices[@]}" -gt 0 ] || {
        if [ "$ACTION" = new ]; then
            die "所有 SSH profiles 已配置；请使用 setup.sh modify"
        fi
        die "没有已配置的 SSH profile；请使用 setup.sh new"
    }
    CLUSTER=$(choose "选择默认集群 profile：" "${cluster_choices[@]}")
fi

if [ "$BACKEND" = ssh ] || [ "$BACKEND" = both ]; then
    [[ "$CLUSTER" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
        || die "集群 profile 名称包含不安全字符"
    export SCNET_HPC_LIVE_NODE_COUNT=no
    load_cluster "$CLUSTER"
    unset SCNET_HPC_LIVE_NODE_COUNT
fi

DEFAULT_BACKEND="$BACKEND"
if [ "$BACKEND" = both ]; then
    backend_default=1
    [ "$saved_backend" != ssh ] || backend_default=2
    DEFAULT_BACKEND=$(SCNET_SETUP_CHOICE_DEFAULT="$backend_default" choose "选择默认 backend：" "openapi" "ssh")
fi

if [ "$BACKEND" = ssh ] || [ "$BACKEND" = both ]; then
    printf '%s\n' \
        "SSH 使用从目标集群控制台下载的私钥文件，不是 AK/SK 授权码，也不是 .pub 公钥。" \
        "用户名应为集群/Linux 用户名；输入私钥文件路径，不要粘贴文件正文。" \
        "将安装到 $HOME/.ssh/id_rsa_${CLUSTER_ID}，配置 $HOME/.ssh/config；不同旧私钥会备份。" \
        "已有非本工具管理的 Host 块会保留；口令私钥请先 ssh-add，过期密钥需重新下载。" >&2
    if [ "$SKIP_CONNECT" = no ]; then
        SSH_KEY="${SSH_KEY:-$(ask "私钥文件路径")}"
        case "$SSH_KEY" in
            \"*\"|\'*\') SSH_KEY="${SSH_KEY:1:${#SSH_KEY}-2}" ;;
        esac
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
    if PYTHON_BIN="$(resolve_python)"; then
        printf '%s\n' \
            "OpenAPI 使用一组平台 AK/SK 自动发现全部授权区域。" >&2
        openapi_args=(setup "$ACTION" --mode openapi)
        [ "$SKIP_CONNECT" = yes ] && openapi_args+=(--skip-connect)
        "$PYTHON_BIN" "$SCRIPT_DIR/scnet.py" "${openapi_args[@]}"
    else
        printf '%s\n' \
            "OpenAPI backend 需要 Python 3。" >&2
        exit 1
    fi
fi

write_ssh_profile
if [ "$BACKEND" = ssh ] || [ "$BACKEND" = both ]; then
    config_path=$(write_config)
    printf '\n已保存配置：%s\n' "$config_path" >&2
fi
printf '下一步：%s/scripts/scnet.py doctor\n' "$REPO_ROOT" >&2
