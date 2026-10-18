#!/usr/bin/env python3
"""Backend-neutral SCNet command-line entrypoint."""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import platform
import re
import select
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from scnet_backends import BackendContext, BackendError, backend_catalog, create_backend
from scnet_backends.profile import list_profiles, load_profile
from scnet_config import (
    config_path,
    load_user_config,
    redacted_config,
    reset_all_metadata,
    reset_openapi_metadata,
    reset_ssh_metadata,
    save_user_config,
)
from scnet_credentials import (
    CredentialError,
    delete_openapi_credentials,
    load_openapi_credentials,
    load_secure_credentials,
    normalize_credential,
    secure_store_name,
    store_openapi_credentials,
)
from scnet_sdk.cli import add_notebook_parser, execute_notebook
from scnet_version import VERSION


REPO_ROOT = Path(__file__).resolve().parent.parent
MUTATING_OPERATIONS = frozenset(
    {"submit", "cancel", "mkdir", "upload", "download", "exec"}
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate SCNet through SSH, OpenAPI, or an external backend adapter."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"scnet-hpc {VERSION}",
    )
    parser.add_argument(
        "--backend",
        help=(
            "backend name; defaults to SCNET_HPC_BACKEND, saved setup choice, "
            "profile DEFAULT_BACKEND, then openapi"
        ),
    )
    parser.add_argument("--cluster", help="local cluster profile name")
    parser.add_argument("--region", help="OpenAPI region ID or name")
    parser.add_argument("--scheduler-id", help="OpenAPI scheduler ID")
    parser.add_argument("--username", help="OpenAPI region username override")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--json", action="store_true", help="emit a JSON envelope")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview a mutation without contacting the selected backend",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="request backend-specific raw fields when supported",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="include full normalized fields and formatted JSON; --raw includes backend data",
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    subparsers.add_parser("backends", help="list built-in and discovered backends")
    subparsers.add_parser(
        "capabilities", help="show capabilities for the selected backend"
    )
    subparsers.add_parser("clusters", help="list local profiles or OpenAPI regions")
    subparsers.add_parser("queues", help="list queues/partitions")
    subparsers.add_parser("config", help="show saved non-secret configuration")
    setup = subparsers.add_parser(
        "setup", help="create, modify, inspect, or reset local configuration"
    )
    setup.add_argument(
        "setup_action",
        nargs="?",
        choices=("auto", "new", "modify", "status", "reset"),
        default="auto",
        help="configuration lifecycle action; default chooses interactively",
    )
    setup.add_argument(
        "--skip-connect",
        action="store_true",
        help="save non-secret choices without testing or changing remote access",
    )
    setup.add_argument(
        "--mode",
        choices=("all", "ssh", "openapi"),
        default="all",
        help="limit the configuration panel to one backend",
    )
    doctor = subparsers.add_parser(
        "doctor", help="check first-use configuration without changing it"
    )
    doctor.add_argument(
        "--no-network",
        action="store_true",
        help="check local configuration only",
    )

    limits = subparsers.add_parser("limits", help="show scheduler or user resource limits")
    limits.add_argument("--partition")

    account = subparsers.add_parser("account", help="show account summary")
    resource_summary = subparsers.add_parser(
        "resource-summary", help="show region resources and limits"
    )

    job = subparsers.add_parser("job", help="show one job")
    job.add_argument("job_id")

    wait = subparsers.add_parser("wait", help="wait for one job to reach a terminal state")
    wait.add_argument("job_id")
    wait.add_argument("--wait-timeout", type=int, default=300)
    wait.add_argument("--interval", type=int, default=10)

    jobs = subparsers.add_parser("jobs", help="list active or historical jobs")
    jobs.add_argument("--scope", choices=("active", "history"), default="active")
    jobs.add_argument("--limit", type=int, default=20)
    jobs.add_argument("--days", type=int, default=30)

    logs = subparsers.add_parser("logs", help="read a log file")
    logs.add_argument("--path", required=True)
    logs.add_argument("--lines", type=int, default=200)
    logs.add_argument("--direction", choices=("head", "tail"), default="tail")
    logs.add_argument("--page", type=int, default=1)
    logs.add_argument("--host-name")

    submit = subparsers.add_parser("submit", help="submit a job")
    submit.add_argument("--remote-path", help="SSH: existing remote Slurm script")
    submit.add_argument("--name", help="OpenAPI: job name")
    submit.add_argument("--command", help="OpenAPI: command or multiline script body")
    submit.add_argument("--work-dir", help="OpenAPI: absolute work directory")
    submit.add_argument("--queue", help="OpenAPI: queue name")
    submit.add_argument("--nodes", type=int, default=1)
    submit.add_argument("--cpus", type=int, default=1)
    submit.add_argument("--gpus", type=int, default=0)
    submit.add_argument("--dcus", type=int, default=0)
    submit.add_argument("--memory")
    submit.add_argument("--walltime", default="24:00:00")
    submit.add_argument("--stdout")
    submit.add_argument("--stderr")
    submit.add_argument("--exclusive", action="store_true")
    submit.add_argument(
        "--scheduler-option",
        dest="scheduler_options",
        action="append",
        default=[],
    )

    cancel = subparsers.add_parser("cancel", help="cancel/delete a job")
    cancel.add_argument("job_id")

    files = subparsers.add_parser("files", help="list remote files (OpenAPI)")
    files.add_argument("--path")
    files.add_argument("--limit", type=int, default=100)
    files.add_argument("--start", type=int, default=0)
    files.add_argument("--order", choices=("asc", "desc"), default="asc")
    files.add_argument(
        "--order-by",
        choices=("name", "size", "lastModifiedTime"),
        default="name",
    )

    upload = subparsers.add_parser("upload", help="upload one file into a remote directory")
    upload.add_argument("local_path")
    upload.add_argument("remote_dir", help="remote destination directory, not a filename")
    upload.add_argument("--cover", action="store_true")
    upload.add_argument(
        "--chunk-size",
        type=int,
        default=8 * 1024 * 1024,
        help="chunked OpenAPI upload threshold and chunk size in bytes; 0 disables",
    )

    mkdir = subparsers.add_parser("mkdir", help="create a remote directory (OpenAPI)")
    mkdir.add_argument("path")
    mkdir.add_argument(
        "--parents",
        action="store_true",
        help="create missing parent directories",
    )

    download = subparsers.add_parser("download", help="download one file or folder")
    download.add_argument("remote_path")
    download.add_argument("local_path", nargs="?")
    download.add_argument("--cover", action="store_true")

    execute = subparsers.add_parser("exec", help="run an SSH command")
    execute.add_argument("command", nargs=argparse.REMAINDER)
    add_notebook_parser(subparsers)
    return parser


def choose_backend(
    explicit: str | None, profile: dict[str, str], user_config: dict[str, Any]
) -> str:
    return (
        explicit
        or os.environ.get("SCNET_HPC_BACKEND")
        or str(user_config.get("default_backend") or "")
        or profile.get("DEFAULT_BACKEND")
        or "openapi"
    )


def _without_empty(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: _without_empty(value) for key, value in data.items()
            if value is not None and value != ""
        }
    if isinstance(data, list):
        return [_without_empty(value) for value in data]
    return data


def summarize_output(operation: str, data: Any) -> Any:
    """Project CLI output only; keep backend/SDK responses available to other callers."""

    def pick(item, keys):
        return _without_empty({key: item[key] for key in keys if key in item})

    if operation in {"job", "wait"} and isinstance(data, dict):
        if isinstance(data.get("job"), dict):
            return {
                "job": summarize_output("job", data["job"]),
                **pick(data, ("waited_seconds", "timed_out")),
            }
        result = pick(
            data,
            (
                "job_id",
                "state",
                "queue",
                "exit_code",
                "reason",
                "state_confirmed",
                "reported_state",
                "waited_seconds",
                "timed_out",
            ),
        )
        if not result.get("queue") and data.get("partition"):
            result["queue"] = data["partition"]
        if "state" in result:
            result["state"] = (
                str(result["state"])
                .split(" BY ", 1)[0]
                .split(" by ", 1)[0]
                .rstrip("+")
            )
        return result
    if operation == "jobs" and isinstance(data, dict):
        return {
            **pick(data, ("total", "scope")),
            "items": [
                summarize_output("job", item) for item in data.get("items", [])
            ],
        }
    if operation == "queues" and isinstance(data, list):
        return [
            pick(
                item,
                (
                    "partition",
                    "availability",
                    "nodes",
                    "free_nodes",
                    "free_cpus",
                    "max_walltime",
                ),
            )
            for item in data
        ]
    if operation in {"upload", "download"} and isinstance(data, dict):
        path = data.get("remote_path")
        if not path and data.get("remote_dir") and data.get("remote_filename"):
            path = str(data["remote_dir"]).rstrip("/") + "/" + str(data["remote_filename"])
        result = {"path": path}
        size = data.get("bytes")
        if size is None and data.get("local_path"):
            local = Path(str(data["local_path"]))
            if local.is_file():
                size = local.stat().st_size
        if size is not None:
            result["bytes"] = size
        return _without_empty(result)
    if operation == "submit" and isinstance(data, dict):
        return pick(data, ("job_id",))
    if operation == "cancel" and isinstance(data, dict):
        return pick(data, ("job_id", "cancelled"))
    if operation == "mkdir" and isinstance(data, dict):
        return pick(data, ("path", "created"))
    if operation == "logs" and isinstance(data, dict):
        return pick(data, ("lines",))
    # Diagnostic and configuration responses retain their schema.
    return data


def compact_output(operation: str, data: Any, *, detailed: bool = False) -> str:
    if operation == "logs" and isinstance(data, dict) and "lines" in data:
        lines = "\n".join(data.get("lines") or [])
        if not detailed:
            return lines
        header = (
            f"# {data.get('path')} "
            f"({data.get('direction')}, {len(data.get('lines') or [])} lines)"
        )
        return header + "\n" + lines
    if operation == "exec" and isinstance(data, dict):
        return str(data.get("stdout") or "")
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        **({"indent": 2} if detailed else {"separators": (",", ":")}),
    )


def _job_terminal(state: Any) -> bool:
    value = str(state or "").upper().split(" BY ", 1)[0].rstrip("+")
    return value in {
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "NODE_ERROR",
        "ABNORMAL",
        "EXITED",
        "DONE",
        "OUT_OF_MEMORY",
        "NODE_FAIL",
    }


def wait_for_job(backend, options: Mapping[str, Any]) -> dict[str, Any]:
    timeout = int(options.get("wait_timeout") or 300)
    interval = int(options.get("interval") or 10)
    if timeout < 1 or timeout > 600:
        raise BackendError("wait_timeout must be between 1 and 600 seconds")
    if interval < 1 or interval > 60:
        raise BackendError("interval must be between 1 and 60 seconds")
    started = time.monotonic()
    while True:
        latest = backend.execute("job", options)
        if isinstance(latest, dict) and _job_terminal(latest.get("state")):
            latest["waited_seconds"] = round(time.monotonic() - started, 1)
            latest["timed_out"] = False
            return latest
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            return {
                "job": latest,
                "waited_seconds": round(elapsed, 1),
                "timed_out": True,
            }
        time.sleep(min(interval, timeout - elapsed))


def error_code_for(text: str) -> str:
    value = str(text).lower()
    if "credentials are not configured" in value or "token" in value and "expired" in value:
        return "AUTHENTICATION_FAILED"
    if "region" in value and ("not available" in value or "missing" in value):
        return "REGION_NOT_FOUND"
    if "scheduler" in value and ("not available" in value or "multiple" in value):
        return "SCHEDULER_NOT_FOUND"
    if "queue" in value and ("not found" in value or "no available" in value):
        return "QUEUE_QUERY_FAILED"
    if "job" in value and ("not found" in value or "no job record" in value):
        return "JOB_NOT_FOUND"
    if "already exists" in value:
        return "FILE_TARGET_EXISTS"
    if "does not exist" in value or "not found" in value and "file" in value:
        return "FILE_NOT_FOUND"
    if "timed out" in value or "timeout" in value:
        return "NETWORK_TIMEOUT"
    return "BACKEND_ERROR"


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _ask_secret(prompt: str) -> str:
    return getpass.getpass(f"{prompt}: ").strip()


def _ask_credential(label: str, *, secret: bool = False, default: str = "") -> str:
    while True:
        value = _ask_secret(label) if secret else _ask(label, default)
        try:
            return normalize_credential(value, label)
        except CredentialError as exc:
            print(f"输入未通过检查：{exc}")


def _credential_help() -> None:
    provider = secure_store_name()
    print("\n凭据保存方式（AK/SK 与 SSH 私钥是两套独立凭据）：")
    if provider == "Windows Credential Manager":
        print("Windows：可保存到当前用户的 Windows 凭据管理器，无需安装额外工具。")
        print("查看/删除：控制面板 → 凭据管理器 → Windows 凭据 → 普通凭据 → scnet-hpc-openapi。")
    elif provider == "macOS Keychain":
        print("macOS：使用系统自带 Keychain，无需安装依赖；系统可能提示解锁或授权访问。")
        print("可在“钥匙串访问”搜索 scnet-hpc-openapi 查看或删除。")
    elif provider == "Secret Service":
        print("Linux：已找到 secret-tool；保存时还需要运行且已解锁的 Secret Service 密钥环。")
        print("仅安装 libsecret-tools 不保证密钥环可用，无桌面/无 D-Bus 的服务器可使用环境变量。")
    else:
        print("当前没有可用的系统凭据工具；仍可校验 AK/SK，但不会自动持久保存。")
        print("Ubuntu/Debian：sudo apt install libsecret-tools；还需桌面密钥环服务运行并解锁。")
    print("环境变量优先于系统凭据库；config.json/openapi.json 只保存账号与区域等非敏感信息。")
    print("PowerShell 的 $env: 设置仅对当前会话及其子进程生效，已启动的桌面应用不会自动获得。")


def _local_cli_command(*arguments: str) -> str:
    """Render a command the user can paste from any working directory."""
    interpreter = "python" if platform.system() == "Windows" else "python3"
    parts = [interpreter, str((REPO_ROOT / "scripts" / "scnet.py").resolve()), *arguments]
    if platform.system() == "Windows":
        # PowerShell single-quoted literals do not expand $, backticks or subexpressions.
        return " ".join("'" + part.replace("'", "''") + "'" if index else part for index, part in enumerate(parts))
    return shlex.join(parts)


def _print_environment_help() -> None:
    if platform.system() == "Windows":
        print("在运行本程序的同一个 PowerShell 中注入；以下占位符需替换为真实值：")
        print('$env:SCNET_OPENAPI_USER = "<平台用户名>"')
        print('$env:SCNET_OPENAPI_ACCESS_KEY = "<AccessKey>"')
        print('$env:SCNET_OPENAPI_SECRET_KEY = "<SecretKey>"')
        print("关闭窗口后失效；日常桌面使用建议重新配置并选择系统凭据库。")
    else:
        print("在运行本程序的同一个 Bash/Zsh 中注入，或使用宿主的秘密注入功能：")
        print('export SCNET_OPENAPI_USER="<平台用户名>"')
        print('export SCNET_OPENAPI_ACCESS_KEY="<AccessKey>"')
        print('export SCNET_OPENAPI_SECRET_KEY="<SecretKey>"')
    print("命令中的秘密可能进入 shell 历史；不要把 AK/SK 写入仓库、普通配置或聊天。")


def _private_key_path(value: str) -> Path:
    value = value.strip()
    if "PRIVATE KEY" in value or "\n" in value or "\r" in value:
        raise BackendError("这里只接受私钥文件路径，不接受私钥正文。")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    path = Path(value).expanduser()
    if not value or path.suffix == ".pub":
        raise BackendError("请选择私钥文件路径，不要选择 .pub 公钥。")
    return path


def _ssh_setup_help(cluster: str, profile: Mapping[str, str]) -> None:
    print("\nSSH 私钥获取：SCNet 控制台选择目标区域 → 命令行 E-Shell → 左上角 SSH 连接。")
    print("下载原始私钥文件（可能以 _rsa.txt 结尾），记录页面上的域名和端口，与下方目标核对。")
    print("官方步骤：https://www2.scnet.cn/help/docs/mainsite/hpc/advanced-guide/advanced-efile/index.html")
    print("AK/SK 授权码不能用于 SSH。集群用户名可在该区域网页 E-Shell 运行 whoami 核对。")
    print("输入文件路径即可（支持空格和外层引号），不要粘贴私钥正文，也不要选择 .pub 公钥。")
    print(f"连接目标：{profile.get('SSH_HOST')}:{profile.get('SSH_PORT', '22')}，别名 {cluster}。")
    print("用户名是该区域的集群/Linux 用户名，可能与 OpenAPI 平台账号不同。")
    print(f"自动安装位置：{Path.home() / '.ssh' / ('id_rsa_' + cluster)}")
    print(f"SSH 配置文件：{Path.home() / '.ssh/config'}")
    print("不同的旧私钥会备份；已有非本工具管理的 Host 块会保留，不会自动改写。")
    if platform.system() == "Windows":
        print("Windows 原生 OpenSSH 与 WSL2 的 ~/.ssh 互相独立；自动安装脚本需在 WSL2 内执行。")
        print("已有 Windows OpenSSH 配置可用 setup modify 接管；手工安装步骤见 references/setup.md。")
    print("若私钥设有口令，先用 ssh-add 加载；连接失败还需检查有效期、端口及平台 IP 白名单。")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def _choose(prompt: str, choices: list[str], default: int = 1) -> str:
    if (
        sys.stdin.isatty()
        and sys.stdout.isatty()
        and os.name == "posix"
        and os.environ.get("TERM", "") != "dumb"
    ):
        return _choose_interactive(prompt, choices, default)

    print(prompt)
    for index, choice in enumerate(choices, 1):
        marker = "*" if index == default else " "
        print(f"  {marker} {index}. {choice}")
    print(f"请输入 1-{len(choices)} 的数字并按 Enter。")
    print(f"直接按 Enter 使用带 * 的默认项 {default}。")
    answer = _ask("选择", str(default))
    try:
        selected = int(answer)
    except ValueError as exc:
        raise BackendError("请输入列表中的数字") from exc
    if selected < 1 or selected > len(choices):
        raise BackendError("选择超出范围")
    return choices[selected - 1]


def _choose_interactive(
    prompt: str, choices: list[str], default: int
) -> str:
    import termios
    import tty

    selected = max(0, min(default - 1, len(choices) - 1))
    number = ""
    line_count = len(choices) + 1

    print(prompt)
    print("使用 ↑/↓ 移动，Enter 确认；也可输入编号后按 Enter；q 取消。")

    def render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\033[{line_count}A")
        for index, choice in enumerate(choices):
            pointer = "▶" if index == selected else " "
            sys.stdout.write(
                f"\r\033[2K  {pointer} {index + 1}. {choice}\n"
            )
        typed = f"编号：{number}" if number else "编号：（可直接按 Enter）"
        sys.stdout.write(f"\r\033[2K  {typed}\n")
        sys.stdout.flush()

    old_settings = termios.tcgetattr(sys.stdin.fileno())
    input_fd = sys.stdin.fileno()
    render(first=True)
    try:
        tty.setcbreak(input_fd)
        while True:
            char = os.read(input_fd, 1).decode("utf-8", "ignore")
            if char in {"\r", "\n"}:
                if number:
                    value = int(number)
                    if 1 <= value <= len(choices):
                        selected = value - 1
                        break
                    number = ""
                    render()
                    continue
                break
            if char == "\x1b":
                ready, _, _ = select.select([input_fd], [], [], 0.1)
                sequence = (
                    os.read(input_fd, 2).decode("utf-8", "ignore")
                    if ready
                    else ""
                )
                if sequence == "[A":
                    selected = (selected - 1) % len(choices)
                    number = ""
                    render()
                elif sequence == "[B":
                    selected = (selected + 1) % len(choices)
                    number = ""
                    render()
                continue
            if char in {"q", "Q", "\x03"}:
                raise BackendError("用户取消配置")
            if char in {"\x7f", "\b"}:
                number = number[:-1]
                render()
                continue
            if char.isdigit():
                number += char
                render()
    finally:
        termios.tcsetattr(
            input_fd, termios.TCSADRAIN, old_settings
        )
    print(f"已选择：{selected + 1}. {choices[selected]}")
    return choices[selected]


def _parse_multi_numbers(value: str, count: int) -> set[int]:
    selected: set[int] = set()
    for part in value.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            selected.update(range(start - 1, end))
        else:
            selected.add(int(part) - 1)
    if not selected or any(index < 0 or index >= count for index in selected):
        raise ValueError("selection out of range")
    return selected


def _multi_choose(
    prompt: str,
    choices: list[str],
    defaults: set[int] | None = None,
) -> list[str]:
    selected = set(defaults or set())
    if (
        sys.stdin.isatty()
        and sys.stdout.isatty()
        and os.name == "posix"
        and os.environ.get("TERM", "") != "dumb"
    ):
        return _multi_choose_interactive(prompt, choices, selected)

    print(prompt)
    for index, choice in enumerate(choices, 1):
        marker = "x" if index - 1 in selected else " "
        print(f"  [{marker}] {index}. {choice}")
    default_text = ",".join(str(index + 1) for index in sorted(selected))
    print("输入编号列表，如 1,3,5-8；直接按 Enter 保留当前勾选。")
    answer = _ask("选择", default_text)
    try:
        indices = _parse_multi_numbers(answer, len(choices))
    except (ValueError, TypeError) as exc:
        raise BackendError("多选格式无效，请输入如 1,3,5-8") from exc
    return [choice for index, choice in enumerate(choices) if index in indices]


def _multi_choose_interactive(
    prompt: str,
    choices: list[str],
    selected: set[int],
) -> list[str]:
    import termios
    import tty

    cursor = min(selected) if selected else 0
    digits = ""
    line_count = len(choices) + 1
    print(prompt)
    print(
        "使用 ↑/↓ 移动，Space 勾选，a 全选，n 清空，"
        "Enter 保存，q 取消。"
    )

    def render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\033[{line_count}A")
        for index, choice in enumerate(choices):
            pointer = "▶" if index == cursor else " "
            checked = "x" if index in selected else " "
            sys.stdout.write(
                f"\r\033[2K  {pointer} [{checked}] {index + 1}. {choice}\n"
            )
        hint = (
            f"编号定位：{digits}"
            if digits
            else f"已选择 {len(selected)}/{len(choices)}"
        )
        sys.stdout.write(f"\r\033[2K  {hint}\n")
        sys.stdout.flush()

    input_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(input_fd)
    render(first=True)
    try:
        tty.setcbreak(input_fd)
        while True:
            char = os.read(input_fd, 1).decode("utf-8", "ignore")
            if char in {"\r", "\n"}:
                if digits:
                    value = int(digits)
                    if 1 <= value <= len(choices):
                        cursor = value - 1
                    digits = ""
                    render()
                    continue
                if selected:
                    break
                render()
                continue
            if char == "\x1b":
                ready, _, _ = select.select([input_fd], [], [], 0.1)
                sequence = (
                    os.read(input_fd, 2).decode("utf-8", "ignore")
                    if ready
                    else ""
                )
                if sequence == "[A":
                    cursor = (cursor - 1) % len(choices)
                    digits = ""
                    render()
                elif sequence == "[B":
                    cursor = (cursor + 1) % len(choices)
                    digits = ""
                    render()
                continue
            if char == " ":
                if cursor in selected:
                    selected.remove(cursor)
                else:
                    selected.add(cursor)
                digits = ""
                render()
                continue
            if char in {"a", "A"}:
                selected = set(range(len(choices)))
                digits = ""
                render()
                continue
            if char in {"n", "N"}:
                selected.clear()
                digits = ""
                render()
                continue
            if char in {"q", "Q", "\x03"}:
                raise BackendError("用户取消配置")
            if char in {"\x7f", "\b"}:
                digits = digits[:-1]
                render()
                continue
            if char.isdigit():
                digits += char
                value = int(digits)
                if 1 <= value <= len(choices):
                    cursor = value - 1
                render()
    finally:
        termios.tcsetattr(input_fd, termios.TCSADRAIN, old_settings)
    print(f"已启用 {len(selected)} 个区域。")
    return [
        choice for index, choice in enumerate(choices) if index in selected
    ]


def _print_terminal_help() -> None:
    system = platform.system()
    if system == "Darwin":
        print(
            "macOS：在 Terminal 或 iTerm2 中可用 ↑/↓ 和 Enter，"
            "也可输入编号；Ctrl+C 可取消。敏感输入不会回显。"
        )
        print("凭据可保存到系统自带的 macOS Keychain。")
    elif system == "Linux":
        distro = ""
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if line.startswith("ID="):
                    distro = line.split("=", 1)[1].strip().strip('"')
                    break
        except OSError:
            pass
        if distro in {"ubuntu", "debian"}:
            print(
                "Ubuntu/Debian：在 Terminal 中可用 ↑/↓ 和 Enter，"
                "也可输入编号；Ctrl+C 可取消。敏感输入不会回显。"
            )
            print(
                "如需安全保存 AK/SK，可安装 Secret Service 工具："
                "sudo apt install libsecret-tools"
            )
        else:
            print(
                "Linux：使用 ↑/↓ 和 Enter，也可输入编号；"
                "Ctrl+C 可取消。敏感输入不会回显。"
            )
    elif system == "Windows":
        print("Windows：输入编号并按 Enter 选择；Ctrl+C 可取消。敏感输入不会回显。")
        print("OpenAPI 配置可直接运行 Python，并保存到 Windows 凭据管理器；无需 Bash。")
        print("SSH 自动安装及完整 shell 脚本环境请使用 WSL2。")
    print()


def _run_setup_ssh(cluster: str, key_path: str, username: str) -> None:
    if platform.system() == "Windows":
        raise BackendError("Windows 原生环境无法执行 SSH 自动安装脚本；请在 WSL2 中运行 setup，或按 references/setup.md 配置 Windows OpenSSH。")
    script = REPO_ROOT / "scripts" / "setup-ssh.sh"
    command = [str(script), "--cluster", cluster, key_path, username]
    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        raise BackendError(f"无法执行 SSH 配置脚本: {exc}") from exc
    if completed.returncode != 0:
        raise BackendError("SSH 配置失败，请根据上面的输出修复后重新运行 setup")


def _with_openapi_credentials(
    profile: dict[str, str],
    *,
    user: str = "",
    access_key: str = "",
    secret_key: str = "",
    token: str = "",
    region_id: str = "",
) -> tuple[Any, dict[str, str | None]]:
    previous = {
        key: os.environ.get(key)
        for key in (
            "SCNET_OPENAPI_USER",
            "SCNET_OPENAPI_ACCESS_KEY",
            "SCNET_OPENAPI_SECRET_KEY",
            "SCNET_OPENAPI_TOKEN",
            "SCNET_OPENAPI_REGION_ID",
        )
    }
    try:
        for key, value in (
            ("SCNET_OPENAPI_USER", user),
            ("SCNET_OPENAPI_ACCESS_KEY", access_key),
            ("SCNET_OPENAPI_SECRET_KEY", secret_key),
            ("SCNET_OPENAPI_TOKEN", token),
            ("SCNET_OPENAPI_REGION_ID", region_id),
        ):
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        context = BackendContext(
            repo_root=REPO_ROOT,
            profile_name=None,
            profile=profile,
            timeout=30,
        )
        backend = create_backend("openapi", context)
        return backend, previous
    except Exception:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        raise


def _restore_environment(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _openapi_probe(
    backend: Any, region: str
) -> dict[str, Any]:
    return backend.discover_region_context(region)


def _key_expiry_from_name(path: str) -> str:
    match = re.search(
        r"RsaKeyExpireTime[_-](\d{4}-\d{2}-\d{2})",
        Path(path).name,
    )
    return match.group(1) if match else ""


def _detect_ssh_username(
    cluster: str,
    profile: Mapping[str, str],
    key_path: str,
    existing: Mapping[str, Any],
) -> str:
    username = str(existing.get("username") or "")
    if username:
        return username
    marker = profile.get("KEY_NAME_MARKER", "")
    filename = Path(key_path).name if key_path else ""
    if marker and "<" not in marker and marker in filename:
        candidate = filename.split(marker, 1)[0]
        if candidate:
            return candidate
    host_marker = f"_{profile.get('SSH_HOST', '')}_"
    if profile.get("SSH_HOST") and host_marker in filename:
        candidate = filename.split(host_marker, 1)[0]
        if candidate:
            return candidate
    if shutil.which("ssh"):
        completed = subprocess.run(
            ["ssh", "-G", cluster],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        resolved: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            key, _, value = line.partition(" ")
            if key in {"hostname", "user"} and value:
                resolved[key] = value
        if (
            completed.returncode == 0
            and resolved.get("hostname") == profile.get("SSH_HOST")
        ):
            return resolved.get("user", "")
    return ""


def _resolved_ssh_connection(
    cluster: str, profile: Mapping[str, str]
) -> dict[str, Any]:
    if not shutil.which("ssh"):
        return {}
    completed = subprocess.run(
        ["ssh", "-G", cluster],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return {}
    values: dict[str, list[str]] = {}
    for line in completed.stdout.splitlines():
        key, _, value = line.partition(" ")
        if value:
            values.setdefault(key, []).append(value)
    host = (values.get("hostname") or [""])[0]
    port = (values.get("port") or [""])[0]
    if host != profile.get("SSH_HOST"):
        return {}
    expected_port = str(profile.get("SSH_PORT") or "22")
    if port and port != expected_port:
        return {}
    identity_files = [
        str(Path(value).expanduser())
        for value in values.get("identityfile", [])
    ]
    existing_key = next(
        (value for value in identity_files if Path(value).is_file()), ""
    )
    return {
        "username": (values.get("user") or [""])[0],
        "hostname": host,
        "port": port or expected_port,
        "key_path": existing_key,
        "detected": bool(existing_key),
    }


def _ssh_key_metadata(
    cluster: str, source: str, username: str, *, installed_path: str | None = None
) -> dict[str, Any]:
    installed = Path(installed_path).expanduser() if installed_path else Path.home() / ".ssh" / f"id_rsa_{cluster}"
    metadata: dict[str, Any] = {
        "username": username,
        "key_path": str(installed),
        "key_source_name": Path(source).name,
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    expiry = _key_expiry_from_name(source)
    if expiry:
        metadata["key_expires_at"] = expiry
    if installed.is_file() and shutil.which("ssh-keygen"):
        completed = subprocess.run(
            ["ssh-keygen", "-lf", str(installed)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode == 0:
            fields = completed.stdout.split()
            if len(fields) >= 2:
                metadata["key_fingerprint"] = fields[1]
    return metadata


def _has_configuration(config: Mapping[str, Any]) -> bool:
    if config.get("default_backend") or config.get("cluster"):
        return True
    ssh = config.get("ssh")
    if isinstance(ssh, dict) and ssh.get("clusters"):
        return True
    return isinstance(config.get("openapi"), dict) and bool(config["openapi"])


def _print_setup_status(config: Mapping[str, Any]) -> None:
    print("\nSCNet HPC 配置状态")
    print("===================")
    print(f"版本：{VERSION}")
    print(f"配置目录：{config_path().parent}")
    print(f"默认 backend：{config.get('default_backend') or '未设置'}")
    print(f"默认 SSH profile：{config.get('cluster') or '未设置'}")
    ssh = config.get("ssh")
    clusters = ssh.get("clusters", {}) if isinstance(ssh, dict) else {}
    print(f"SSH profiles：{len(clusters) if isinstance(clusters, dict) else 0}")
    if isinstance(clusters, dict):
        for name, profile in sorted(clusters.items()):
            if not isinstance(profile, dict):
                continue
            expiry = profile.get("key_expires_at") or "未知"
            print(
                f"  - {name}: user={profile.get('username') or '未知'}, "
                f"key={profile.get('key_path') or '未安装/未记录'}, key_expires={expiry}"
            )
    configured_names = set(clusters) if isinstance(clusters, dict) else set()
    for item in list_profiles(REPO_ROOT):
        name = item["name"]
        if name in configured_names:
            continue
        _, profile = load_profile(REPO_ROOT, name)
        detected = _resolved_ssh_connection(name, profile)
        if detected:
            print(
                f"  - {name}: 已检测到本机 SSH 连接，"
                f"user={detected.get('username') or '未知'}, "
                f"key={detected.get('key_path') or '未知'} "
                "(尚未纳入元数据)"
            )
    openapi = config.get("openapi")
    if isinstance(openapi, dict) and openapi:
        regions = openapi.get("regions")
        regions = regions if isinstance(regions, dict) else {}
        enabled = openapi.get("enabled_region_ids")
        enabled = enabled if isinstance(enabled, list) else list(regions)
        default_region = str(
            openapi.get("default_region_id")
            or openapi.get("region_id")
            or ""
        )
        print(
            f"OpenAPI：user={openapi.get('platform_user') or '未知'}, "
            f"provider={openapi.get('credential_provider') or '环境变量'}"
        )
        try:
            active_credentials, active_provider = load_openapi_credentials()
            print(f"  当前进程实际凭据来源：{active_provider if active_credentials else '未检测到凭据（区域缓存不等于已认证）'}")
        except CredentialError as exc:
            print(f"  当前凭据检查失败：{exc}")
        print(f"  已发现区域：{len(regions)}，已启用区域：{len(enabled)}")
        for region_id in enabled:
            region = regions.get(str(region_id), {})
            marker = "*" if str(region_id) == default_region else " "
            print(
                f"  {marker} {region.get('name') or region_id} ({region_id})"
            )
    else:
        print("OpenAPI：未配置")


def _setup_reset_panel(config: dict[str, Any]) -> dict[str, Any]:
    choices = [
        "OpenAPI 区域缓存和默认项",
        "OpenAPI 安全凭据（Windows 凭据管理器/Keychain/Secret Service）",
        "一个 SSH profile 的本地元数据",
        "全部 SCNet HPC 本地元数据（不删除真实 SSH key/config）",
    ]
    selected = _choose("选择重置范围：", choices, 1)
    if not _ask_yes_no(f"确认重置“{selected}”？", default=False):
        raise BackendError("用户取消重置")
    if selected.startswith("OpenAPI 区域"):
        reset_openapi_metadata()
        config.pop("openapi", None)
        if config.get("default_backend") == "openapi":
            config["default_backend"] = "ssh"
        save_user_config(config)
    elif selected.startswith("OpenAPI 安全"):
        try:
            deleted, provider = delete_openapi_credentials()
        except CredentialError as exc:
            raise BackendError(str(exc)) from exc
        print(
            f"{provider or '安全凭据库'}："
            f"{'已删除' if deleted else '没有可删除的凭据'}"
        )
    elif selected.startswith("一个 SSH"):
        ssh = config.get("ssh")
        clusters = ssh.get("clusters", {}) if isinstance(ssh, dict) else {}
        if not isinstance(clusters, dict) or not clusters:
            raise BackendError("没有已保存的 SSH profile 元数据")
        names = sorted(clusters)
        name = _choose("选择 SSH profile：", names, 1)
        reset_ssh_metadata(name)
        clusters.pop(name, None)
        if config.get("cluster") == name:
            config["cluster"] = next(iter(clusters), "")
        save_user_config(config)
        print("仅删除本地元数据；~/.ssh 中的 key 和 config 保持不变。")
    else:
        removed = reset_all_metadata()
        print(f"已删除 {len(removed)} 个本地配置文件。")
    return load_user_config()


def setup_lifecycle(
    action: str, mode: str, skip_connect: bool
) -> dict[str, Any]:
    current = load_user_config()
    exists = _has_configuration(current)
    if action == "auto":
        labels = [
            "查看当前状态（status）",
            "新增连接（new）",
            "修改现有配置（modify）",
            "重置配置（reset）",
        ]
        default = 3 if exists else 2
        selected = _choose("选择配置操作：", labels, default)
        action = selected.split("（", 1)[1].split("）", 1)[0]
    if action == "status":
        _print_setup_status(current)
        return current
    if action == "reset":
        return _setup_reset_panel(current)
    if action == "modify" and not exists:
        raise BackendError("尚无配置，请使用 `setup new`")
    setup_panel._skip_connect = skip_connect
    return setup_panel(mode, action)


def setup_panel(
    mode: str = "all", action: str = "modify"
) -> dict[str, Any]:
    profiles = list_profiles(REPO_ROOT)
    if not profiles:
        raise BackendError("clusters/ 下没有 profile")
    current = load_user_config()
    print("\nSCNet HPC 配置/维护面板")
    print("=======================")
    print("自动探测区域、调度器和 SSH 元数据；只要求输入必要凭据。\n")
    _print_terminal_help()

    current_default = str(current.get("default_backend") or "openapi")
    if mode == "all":
        backend = _choose(
            "选择默认 backend：",
            ["OpenAPI（推荐，结构化控制面）", "SSH（环境配置和深度诊断）"],
            1 if current_default == "openapi" else 2,
        )
        default_backend = "openapi" if backend.startswith("OpenAPI") else "ssh"
        configure_ssh = _ask_yes_no(
            "是否添加或更新一个 SSH 区域？", default=default_backend == "ssh"
        )
        configure_openapi = _ask_yes_no(
            "是否配置或刷新 OpenAPI？", default=default_backend == "openapi"
        )
    else:
        default_backend = mode
        configure_ssh = mode == "ssh"
        configure_openapi = mode == "openapi"

    result: dict[str, Any] = dict(current)
    result.update({"version": 1, "default_backend": default_backend})
    skip_connect = bool(getattr(setup_panel, "_skip_connect", False))
    selected_cluster = str(current.get("cluster") or "")

    if configure_ssh:
        existing_ssh = current.get("ssh", {})
        if not isinstance(existing_ssh, dict):
            existing_ssh = {}
        existing_clusters = existing_ssh.get("clusters", {})
        if not isinstance(existing_clusters, dict):
            existing_clusters = {}
        all_profile_names = [item["name"] for item in profiles]
        detected_connections = {
            name: _resolved_ssh_connection(name, load_profile(REPO_ROOT, name)[1])
            for name in all_profile_names
        }
        detected_connections = {
            name: value for name, value in detected_connections.items() if value
        }
        if action == "new":
            profile_names = [
                name
                for name in all_profile_names
                if name not in existing_clusters and name not in detected_connections
            ]
            if not profile_names:
                raise BackendError(
                    "所有 SSH profiles 已配置或已被检测到；请使用 `setup modify`"
                )
        else:
            profile_names = [
                name
                for name in all_profile_names
                if name in existing_clusters or name in detected_connections
            ]
            if not profile_names:
                raise BackendError(
                    "没有已配置的 SSH profile；请使用 `setup new`"
                )
        default_cluster = (
            profile_names.index(selected_cluster) + 1
            if selected_cluster in profile_names
            else 1
        )
        cluster = _choose("选择要配置或更新的 SSH 区域：", profile_names, default_cluster)
        selected_cluster = cluster
        result["cluster"] = cluster
        _, profile = load_profile(REPO_ROOT, cluster)
        _ssh_setup_help(cluster, profile)
        existing_profile = existing_clusters.get(cluster, {})
        if not isinstance(existing_profile, dict):
            existing_profile = {}
        detected_connection = detected_connections.get(cluster, {})
        if not existing_profile and detected_connection:
            print(
                "\n检测到已有 SSH 连接，将接管其本地元数据：\n"
                f"  用户：{detected_connection.get('username') or '未知'}\n"
                f"  主机：{detected_connection.get('hostname')}:"
                f"{detected_connection.get('port')}\n"
                f"  私钥：{detected_connection.get('key_path') or '未找到'}"
            )
            existing_profile = dict(detected_connection)
        key_path = ""
        if not skip_connect:
            detected_key = str(existing_profile.get("key_path") or "")
            if platform.system() == "Windows" and not detected_connection:
                raise BackendError("尚未检测到 Windows OpenSSH 连接。请先按 references/setup.md 手工配置，或在 WSL2 运行 SSH 安装向导。")
            if action == "modify" and detected_key:
                rotate = _ask_yes_no(
                    "是否轮换为新的 SSH 私钥？", default=False
                )
                key_path = (
                    str(_private_key_path(_ask("新私钥文件路径")))
                    if rotate
                    else detected_key
                )
            else:
                key_path = str(_private_key_path(_ask("私钥文件路径")))
            if not key_path or not Path(key_path).is_file():
                raise BackendError(f"找不到私钥文件: {key_path}")
        detected_user = _detect_ssh_username(
            cluster, profile, key_path, existing_profile
        )
        username = _ask(
            "远端用户名（已自动探测，可直接回车）",
            detected_user,
        )
        if not username:
            raise BackendError("无法自动探测 SSH 用户名，请手工输入")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", username):
            raise BackendError("集群用户名包含空白或不支持的字符，请只填写用户名。")
        print(f"配置摘要：集群={cluster}，用户={username}，私钥={key_path or '未安装（skip-connect）'}")
        clusters = dict(existing_clusters)
        clusters[cluster] = {**existing_profile, "username": username}
        result["ssh"] = {"clusters": clusters}
        if skip_connect:
            print("已按 --skip-connect 跳过私钥安装和 SSH 测试。")
        else:
            adopted = (
                action == "modify"
                and bool(detected_connection)
                and key_path == detected_connection.get("key_path")
            )
            prompt = (
                "确认接管已有 SSH 连接并测试？"
                if adopted
                else "确认安装/轮换私钥并测试连接？"
            )
            if not _ask_yes_no(prompt, default=True):
                print("已跳过 SSH 写入；可稍后单独运行 setup-ssh.sh。")
            elif adopted:
                if username != detected_connection.get("username"):
                    raise BackendError("接管时输入的用户名与现有 SSH 别名不同；请先修改 ~/.ssh/config，再重新运行 setup。")
                completed = subprocess.run(
                    [
                        "ssh",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "ConnectTimeout=20",
                        cluster,
                        "printf SCNET_OK",
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if completed.returncode != 0:
                    raise BackendError(
                        completed.stderr.strip() or "已有 SSH 连接测试失败"
                    )
                clusters[cluster] = {
                    **existing_profile,
                    **_ssh_key_metadata(cluster, key_path, username, installed_path=key_path),
                    "adopted": True,
                }
            else:
                _run_setup_ssh(cluster, key_path, username)
                clusters[cluster] = _ssh_key_metadata(
                    cluster, key_path, username
                )

    if configure_openapi:
        existing_openapi = current.get("openapi", {})
        if not isinstance(existing_openapi, dict):
            existing_openapi = {}
        if action == "new" and existing_openapi:
            raise BackendError(
                "OpenAPI 已配置；请使用 `setup modify --mode openapi`"
            )
        if action == "modify" and not existing_openapi:
            raise BackendError(
                "OpenAPI 尚未配置；请使用 `setup new --mode openapi`"
            )
        if skip_connect:
            print("已按 --skip-connect 跳过 OpenAPI 认证和区域发现。")
        else:
            print(
                "\n当前配置的是 HPC/Slurm 作业 OpenAPI，"
                "不是 Notebook、容器或模型服务 API。"
            )
            print(
                "AK/SK 获取：登录 SCNet → 个人中心 → 访问控制 → "
                "生成并下载授权码。"
            )
            print(
                "官方说明：https://www.scnet.cn/ac/openapi/doc/2.0/"
                "api/safecertification/get-user-tokens-aksk.html"
            )
            _credential_help()
            print("字段对应：平台用户名 = SCNet 平台用户名；AK = 下载文件的 Accesskey 列；SK = Secretkey 列。")
            print("无需填写区域 ID 或接口地址，认证后自动发现已授权区域；账号需已开通区域资源。")
            print("\n请依次复制平台用户名、AccessKey、SecretKey 的值；不需要输入 export 或 $env: 命令。")
            print("AccessKey 和 SecretKey 都不会显示字符或星号；外层引号会自动去除。\n")
            try:
                saved_credentials, saved_provider = load_openapi_credentials()
            except CredentialError as exc:
                print(f"现有凭据无法使用：{exc}")
                saved_credentials, saved_provider = None, None
            use_saved = bool(saved_credentials) and _ask_yes_no(
                f"检测到 {saved_provider} 中的 OpenAPI 凭据，是否使用？",
                default=True,
            )
            entered_credentials = not use_saved
            if use_saved and saved_credentials:
                api_user = saved_credentials["user"]
                access_key = saved_credentials["access_key"]
                secret_key = saved_credentials["secret_key"]
            else:
                api_user = _ask_credential(
                    "平台用户名",
                    default=str(existing_openapi.get("platform_user") or ""),
                )
                while True:
                    access_key = _ask_credential("AccessKey", secret=True)
                    secret_key = _ask_credential("SecretKey", secret=True)
                    if access_key != secret_key:
                        break
                    print("AccessKey 与 SecretKey 完全相同，可能重复粘贴了同一个字段，请重新输入。")
            print(f"账号：{api_user}；AK/SK 已读取且不回显。下一步只读校验认证并发现授权区域。")
            backend_instance, previous = _with_openapi_credentials(
                {},
                user=api_user,
                access_key=access_key,
                secret_key=secret_key,
            )
            try:
                contexts = backend_instance.discover_all_region_contexts()
                if not contexts:
                    raise BackendError("账号没有可用的 OpenAPI 计算区域")
                print("\n已自动发现支持 HPC/Slurm 作业 API 的授权区域：")
                for item in contexts:
                    scheduler_names = ", ".join(
                        str(scheduler.get("name") or scheduler.get("id"))
                        for scheduler in item["schedulers"]
                    )
                    print(
                        f"  - {item.get('name')} ({item['region_id']})"
                        f" / user={item.get('username')}"
                        f" / scheduler={scheduler_names or 'none'}"
                    )
                region_labels = [
                    f"{item.get('name')} ({item['region_id']})"
                    for item in contexts
                ]
                existing_enabled = existing_openapi.get("enabled_region_ids")
                if isinstance(existing_enabled, list):
                    enabled_ids = {str(item) for item in existing_enabled}
                elif action == "new":
                    enabled_ids = {item["region_id"] for item in contexts}
                else:
                    enabled_ids = {
                        str(item)
                        for item in (existing_openapi.get("regions") or {})
                    }
                default_enabled = {
                    index
                    for index, item in enumerate(contexts)
                    if item["region_id"] in enabled_ids
                }
                selected_labels = _multi_choose(
                    "选择在本机启用的 HPC 区域（可多选）：",
                    region_labels,
                    default_enabled,
                )
                selected_label_set = set(selected_labels)
                enabled_contexts = [
                    item
                    for item, label in zip(contexts, region_labels)
                    if label in selected_label_set
                ]
                existing_region = str(
                    existing_openapi.get("default_region_id")
                    or existing_openapi.get("region_id")
                    or ""
                )
                default_region = next(
                    (
                        index
                        for index, item in enumerate(enabled_contexts, 1)
                        if item["region_id"] == existing_region
                    ),
                    1,
                )
                enabled_labels = [
                    f"{item.get('name')} ({item['region_id']})"
                    for item in enabled_contexts
                ]
                selected_label = _choose(
                    "从已启用区域中选择默认 HPC 作业区域（单选）：",
                    enabled_labels,
                    default_region,
                )
                selected_index = enabled_labels.index(selected_label)
                selected = enabled_contexts[selected_index]
            finally:
                _restore_environment(previous)
            stored_provider = saved_provider if use_saved else None
            if (entered_credentials or saved_provider == "environment") and secure_store_name():
                if _ask_yes_no(
                    f"是否将 AK/SK 保存到 {secure_store_name()}？",
                    default=True,
                ):
                    try:
                        provider = store_openapi_credentials(
                            api_user, access_key, secret_key
                        )
                        expected = {"user": api_user, "access_key": access_key, "secret_key": secret_key}
                        if load_secure_credentials() != expected:
                            raise CredentialError("保存后读回校验失败；尚不能确认凭据已持久保存。")
                        stored_provider = provider
                        print(f"OpenAPI 凭据已保存到 {provider}。")
                    except CredentialError as exc:
                        print(f"无法保存到安全凭据库：{exc}")
            if stored_provider is None:
                print("凭据未保存：本次认证已完成，但后续命令仍需注入环境变量或重新保存 AK/SK。")
                _print_environment_help()
            elif stored_provider == "environment":
                print("凭据来源：当前进程环境变量；未另存到系统凭据库，重启后需由宿主重新注入。")
            else:
                print(f"持久保存已验证：{stored_provider}；条目名 scnet-hpc-openapi。")
                if any(os.environ.get(key) for key in ("SCNET_OPENAPI_USER", "SCNET_OPENAPI_ACCESS_KEY", "SCNET_OPENAPI_SECRET_KEY")):
                    print("注意：当前 shell 仍有环境变量，它们优先于刚保存的凭据；请清除旧变量后运行 doctor。")
            selected_schedulers = selected.get("schedulers") or []
            default_scheduler = (
                selected_schedulers[0].get("id")
                if len(selected_schedulers) == 1
                else ""
            )
            result["openapi"] = {
                "platform_user": api_user,
                "credential_provider": stored_provider or "not_saved",
                "default_region_id": selected["region_id"],
                "enabled_region_ids": [
                    item["region_id"] for item in enabled_contexts
                ],
                "region_id": selected["region_id"],
                "region_name": selected.get("name"),
                "scheduler_id": default_scheduler,
                "username": selected.get("username"),
                "regions": {
                    item["region_id"]: {
                        "name": item.get("name"),
                        "available": True,
                        "username": item.get("username"),
                        "home_path": item.get("home_path"),
                        "schedulers": item.get("schedulers"),
                    }
                    for item in contexts
                },
            }
            print(
                "\nHPC OpenAPI 区域选择结果（凭据状态见上方）：\n"
                f"  默认区域：{selected.get('name') or selected['region_id']}"
                f" ({selected['region_id']})\n"
                f"  区域用户：{selected.get('username')}\n"
                f"  Home：{selected.get('home_path')}\n"
                f"  Scheduler："
                f"{', '.join(str(item.get('name') or item.get('id')) for item in selected_schedulers) or '未发现'}\n"
                "  API 类型：HPC/Slurm 作业 API（非 Notebook API）"
            )

    if selected_cluster:
        result["cluster"] = selected_cluster
    path = save_user_config(result)
    print(f"\n已保存非敏感配置：{path}")
    print(f"查看配置：{_local_cli_command('config')}")
    doctor_cluster = selected_cluster or str(current.get("cluster") or "")
    arguments = ["--backend", default_backend]
    if doctor_cluster:
        arguments.extend(["--cluster", doctor_cluster])
    print(f"下一步：{_local_cli_command(*arguments, 'doctor')}")
    return result


def doctor_report(
    backend_name: str,
    profile_name: str | None,
    profile: dict[str, str],
    user_config: dict[str, Any],
    *,
    no_network: bool,
    timeout: int,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    try:
        path = config_path()
        if path.is_file():
            if os.name == "posix":
                mode = path.stat().st_mode & 0o777
                add(
                    "user_config",
                    mode & 0o077 == 0,
                    f"{path} mode={mode:03o}",
                )
            else:
                add(
                    "user_config",
                    True,
                    f"{path}（非 POSIX，跳过 mode 检查；未验证 ACL）",
                )
        else:
            add("user_config", False, f"{path} 不存在；先运行 setup")
    except OSError as exc:
        add("user_config", False, str(exc))

    profile_required = backend_name == "ssh"
    add(
        "profile",
        bool(profile_name and profile.get("CLUSTER_ID"))
        if profile_required
        else True,
        (profile_name or "未选择集群 profile")
        if profile_required
        else "OpenAPI 不需要 SSH profile",
    )
    add(
        "backend",
        backend_name in {item["name"] for item in backend_catalog()},
        backend_name,
    )

    if backend_name == "ssh":
        for command in ("ssh", "scp"):
            executable = shutil.which(command)
            add(command, bool(executable), executable or f"找不到 {command}")
        alias = profile.get("CLUSTER_ID")
        if alias and shutil.which("ssh"):
            completed = subprocess.run(
                ["ssh", "-G", alias],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            resolved = {}
            for line in completed.stdout.splitlines():
                field, _, value = line.partition(" ")
                if field in {"hostname", "port", "user", "identityfile"}:
                    resolved.setdefault(field, value)
            config_ok = (
                completed.returncode == 0
                and resolved.get("hostname") == profile.get("SSH_HOST")
                and resolved.get("port") == str(profile.get("SSH_PORT") or "22")
            )
            detail = (
                f"alias={alias}, host={resolved.get('hostname', '未知')}, "
                f"port={resolved.get('port', '未知')}, user={resolved.get('user', '未知')}, "
                f"key={resolved.get('identityfile', '未配置')}"
            )
            if not config_ok:
                detail += "; 别名未解析到 profile 的主机/端口，请检查当前环境的 ~/.ssh/config"
            add("ssh_config", config_ok, detail)
            if not no_network:
                completed = subprocess.run(
                    [
                        "ssh",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "StrictHostKeyChecking=yes",
                        "-o",
                        f"ConnectTimeout={min(timeout, 20)}",
                        alias,
                        "printf SCNET_OK",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                add(
                    "ssh_connection",
                    completed.returncode == 0
                    and completed.stdout.strip() == "SCNET_OK",
                    "连接成功"
                    if completed.returncode == 0
                    else (completed.stderr.strip() or "连接失败"),
                )
            ssh_config = user_config.get("ssh", {})
            ssh_clusters = (
                ssh_config.get("clusters", {})
                if isinstance(ssh_config, dict)
                else {}
            )
            metadata = (
                ssh_clusters.get(profile_name, {})
                if isinstance(ssh_clusters, dict) and profile_name
                else {}
            )
            if isinstance(metadata, dict):
                key_path = metadata.get("key_path")
                if key_path:
                    expanded = Path(str(key_path)).expanduser()
                    add(
                        "ssh_key",
                        expanded.is_file(),
                        str(expanded) if expanded.is_file() else f"找不到 {expanded}",
                    )
                expiry = metadata.get("key_expires_at")
                if expiry:
                    try:
                        expiry_date = dt.date.fromisoformat(str(expiry))
                        days = (expiry_date - dt.date.today()).days
                        add(
                            "ssh_key_expiry",
                            days >= 0,
                            f"{expiry}（剩余 {days} 天）"
                            if days >= 0
                            else f"{expiry}（已过期 {abs(days)} 天）",
                        )
                    except ValueError:
                        add("ssh_key_expiry", False, f"无法解析日期: {expiry}")
        elif not no_network:
            add("ssh_connection", False, "缺少 profile 或 ssh 命令")

    elif backend_name == "openapi":
        has_token = bool(os.environ.get("SCNET_OPENAPI_TOKEN"))
        try:
            credentials, credential_provider = load_openapi_credentials()
        except CredentialError as exc:
            credentials, credential_provider = None, None
            add("credential_store", False, str(exc))
        has_aksk = bool(credentials)
        add(
            "openapi_credentials",
            has_token or has_aksk,
            "检测到区域 token"
            if has_token
            else (
                f"检测到 AK/SK（{credential_provider}）"
                if has_aksk
                else "未检测到可用凭据；运行 setup new/modify --mode openapi，或同时注入三项环境变量"
            ),
        )
        openapi_config = user_config.get("openapi", {})
        region = (
            (
                openapi_config.get("default_region_id")
                or openapi_config.get("region_id")
            )
            if isinstance(openapi_config, dict)
            else None
        )
        add("openapi_region", bool(region), str(region or "未配置区域"))
        cached_regions = (
            openapi_config.get("regions")
            if isinstance(openapi_config, dict)
            else None
        )
        if isinstance(cached_regions, dict):
            add(
                "openapi_region_cache",
                bool(cached_regions),
                f"已缓存区域数={len(cached_regions)}",
            )
        if not no_network and (has_token or has_aksk):
            context = BackendContext(
                repo_root=REPO_ROOT,
                profile_name=profile_name,
                profile=profile,
                timeout=timeout,
            )
            try:
                backend = create_backend("openapi", context)
                regions = backend.execute("clusters", {})
                add("openapi_connection", True, f"可访问区域数={len(regions)}")
                if region:
                    options = {
                        "region": region,
                        "scheduler_id": openapi_config.get("scheduler_id"),
                        "username": openapi_config.get("username"),
                    }
                    queues = backend.execute("queues", options)
                    add("openapi_queues", True, f"可访问队列数={len(queues)}")
            except BackendError as exc:
                add("openapi_connection", False, str(exc))

    else:
        try:
            context = BackendContext(
                repo_root=REPO_ROOT,
                profile_name=profile_name,
                profile=profile,
                timeout=timeout,
            )
            backend = create_backend(backend_name, context)
            add(
                "external_backend",
                True,
                ", ".join(sorted(backend.capabilities)),
            )
        except BackendError as exc:
            add("external_backend", False, str(exc))

    return {
        "ok": all(item["ok"] for item in checks),
        "backend": backend_name,
        "cluster": profile_name,
        "checks": checks,
    }


def apply_openapi_defaults(
    options: dict[str, Any], openapi_config: Mapping[str, Any]
) -> dict[str, Any]:
    region = (
        options.get("region")
        or openapi_config.get("default_region_id")
        or openapi_config.get("region_id")
    )
    options["region"] = region
    region_config: Mapping[str, Any] = {}
    regions = openapi_config.get("regions")
    if isinstance(regions, dict) and region:
        candidate = regions.get(str(region))
        if isinstance(candidate, dict):
            region_config = candidate
    default_region = str(
        openapi_config.get("default_region_id")
        or openapi_config.get("region_id")
        or ""
    )
    scheduler_id = options.get("scheduler_id")
    if not scheduler_id and str(region or "") == default_region:
        scheduler_id = openapi_config.get("scheduler_id")
    schedulers = region_config.get("schedulers")
    if not scheduler_id and isinstance(schedulers, list):
        available = [
            item
            for item in schedulers
            if isinstance(item, dict) and item.get("id")
        ]
        if len(available) == 1:
            scheduler_id = available[0]["id"]
    options["scheduler_id"] = scheduler_id
    options["username"] = (
        options.get("username")
        or region_config.get("username")
        or (
            openapi_config.get("username")
            if str(region or "") == default_region
            else None
        )
    )
    return options


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout < 1 or args.timeout > 3600:
        parser.error("--timeout must be between 1 and 3600 seconds")

    try:
        user_config = load_user_config()
        selected_cluster = args.cluster or str(user_config.get("cluster") or "") or None
        if args.operation == "backends":
            data = backend_catalog()
            backend_name = None
        elif args.operation == "setup":
            data = setup_lifecycle(
                args.setup_action,
                args.mode,
                args.skip_connect,
            )
            backend_name = data.get("default_backend")
        elif args.operation == "config":
            data = redacted_config(user_config)
            backend_name = None
        else:
            profile_name, profile = load_profile(REPO_ROOT, selected_cluster)
            backend_name = choose_backend(args.backend, profile, user_config)
            context = BackendContext(
                repo_root=REPO_ROOT,
                profile_name=profile_name,
                profile=profile,
                timeout=args.timeout,
            )
            backend = create_backend(backend_name, context)
            options = vars(args).copy()
            openapi_config = user_config.get("openapi", {})
            if isinstance(openapi_config, dict):
                apply_openapi_defaults(options, openapi_config)
            if args.operation == "download" and not options.get("local_path"):
                remote_path = str(options.get("remote_path") or "").rstrip("/")
                options["local_path"] = remote_path.rsplit("/", 1)[-1] or "download"
            if args.operation == "notebook":
                if backend_name != "openapi":
                    raise BackendError(
                        "Notebook management requires the OpenAPI backend"
                    )
                data = execute_notebook(args, context, user_config)
            elif args.dry_run:
                if args.operation not in MUTATING_OPERATIONS:
                    raise BackendError(
                        "--dry-run 仅适用于 submit/cancel/mkdir/upload/download/exec"
                    )
                data = backend.preview(args.operation, options)
            elif args.operation == "doctor":
                data = doctor_report(
                    backend_name,
                    profile_name,
                    profile,
                    user_config,
                    no_network=args.no_network,
                    timeout=args.timeout,
                )
            elif args.operation == "capabilities":
                data = {
                    "name": backend.name,
                    "capabilities": sorted(backend.capabilities),
                }
            elif args.operation == "wait":
                data = wait_for_job(backend, options)
            elif args.operation == "exec":
                options["command"] = " ".join(args.command).strip()
                data = backend.execute(args.operation, options)
            else:
                data = backend.execute(args.operation, options)
        detailed = args.details or args.raw or args.dry_run
        output_data = data if detailed else summarize_output(args.operation, data)
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "version": VERSION,
                        "backend": backend_name,
                        "operation": args.operation,
                        "data": output_data,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    **({"indent": 2} if detailed else {"separators": (",", ":")}),
                )
            )
        elif args.operation != "setup":
            print(compact_output(args.operation, output_data, detailed=detailed))
        if args.operation == "doctor" and not data.get("ok", False):
            return 1
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\n已取消输入；未完成的配置请重新运行 setup。", file=sys.stderr)
        return 130
    except (BackendError, CredentialError) as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "operation": args.operation,
                        "error_code": error_code_for(str(exc)),
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
