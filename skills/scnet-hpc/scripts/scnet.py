#!/usr/bin/env python3
"""Backend-neutral SCNet command-line entrypoint."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from scnet_backends import BackendContext, BackendError, backend_catalog, create_backend
from scnet_backends.profile import list_profiles, load_profile
from scnet_config import (
    config_path,
    load_user_config,
    redacted_config,
    save_user_config,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
MUTATING_OPERATIONS = frozenset(
    {"submit", "cancel", "mkdir", "upload", "download", "exec"}
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate SCNet through SSH, OpenAPI, or an external backend adapter."
    )
    parser.add_argument(
        "--backend",
        help=(
            "backend name; defaults to SCNET_HPC_BACKEND, saved setup choice, "
            "profile DEFAULT_BACKEND, then ssh"
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
    subparsers = parser.add_subparsers(dest="operation", required=True)

    subparsers.add_parser("backends", help="list built-in and discovered backends")
    subparsers.add_parser(
        "capabilities", help="show capabilities for the selected backend"
    )
    subparsers.add_parser("clusters", help="list local profiles or OpenAPI regions")
    subparsers.add_parser("queues", help="list queues/partitions")
    subparsers.add_parser("config", help="show saved non-secret configuration")
    setup = subparsers.add_parser(
        "setup", help="open the first-use terminal configuration panel"
    )
    setup.add_argument(
        "--skip-connect",
        action="store_true",
        help="save non-secret choices without testing or changing remote access",
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

    job = subparsers.add_parser("job", help="show one job")
    job.add_argument("job_id")

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

    upload = subparsers.add_parser("upload", help="upload one file")
    upload.add_argument("local_path")
    upload.add_argument("remote_path")
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
    download.add_argument("local_path")
    download.add_argument("--cover", action="store_true")

    execute = subparsers.add_parser("exec", help="run an SSH command")
    execute.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def choose_backend(
    explicit: str | None, profile: dict[str, str], user_config: dict[str, Any]
) -> str:
    return (
        explicit
        or os.environ.get("SCNET_HPC_BACKEND")
        or str(user_config.get("default_backend") or "")
        or profile.get("DEFAULT_BACKEND")
        or "ssh"
    )


def compact_output(operation: str, data: Any) -> str:
    if operation == "logs" and isinstance(data, dict):
        header = (
            f"# {data.get('path')} "
            f"({data.get('direction')}, {len(data.get('lines') or [])} lines)"
        )
        return header + "\n" + "\n".join(data.get("lines") or [])
    if operation == "exec" and isinstance(data, dict):
        return str(data.get("stdout") or "")
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _ask_secret(prompt: str) -> str:
    return getpass.getpass(f"{prompt}: ").strip()


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def _choose(prompt: str, choices: list[str], default: int = 1) -> str:
    print(prompt)
    for index, choice in enumerate(choices, 1):
        marker = "*" if index == default else " "
        print(f"  {marker} {index}. {choice}")
    answer = _ask("选择", str(default))
    try:
        selected = int(answer)
    except ValueError as exc:
        raise BackendError("请输入列表中的数字") from exc
    if selected < 1 or selected > len(choices):
        raise BackendError("选择超出范围")
    return choices[selected - 1]


def _run_setup_ssh(cluster: str, key_path: str, username: str) -> None:
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


def setup_panel() -> dict[str, Any]:
    profiles = list_profiles(REPO_ROOT)
    if not profiles:
        raise BackendError("clusters/ 下没有 profile")
    current = load_user_config()
    print("\nSCNet HPC 首次配置面板")
    print("======================")
    print("只保存非敏感配置；AK/SK/token 仅用于本次验证，不会写入配置文件。\n")

    profile_names = [item["name"] for item in profiles]
    current_cluster = str(current.get("cluster") or "")
    default_cluster = (
        profile_names.index(current_cluster) + 1
        if current_cluster in profile_names
        else 1
    )
    cluster = _choose("选择默认集群 profile：", profile_names, default_cluster)
    _, profile = load_profile(REPO_ROOT, cluster)

    backend = _choose(
        "选择默认 backend：",
        ["SSH（推荐，支持环境和深度诊断）", "OpenAPI（结构化控制面）"],
        1 if current.get("default_backend", "ssh") == "ssh" else 2,
    )
    default_backend = "ssh" if backend.startswith("SSH") else "openapi"
    configure_ssh = _ask_yes_no(
        "是否配置 SSH backend？", default=default_backend == "ssh"
    )
    configure_openapi = _ask_yes_no(
        "是否验证 OpenAPI backend？", default=default_backend == "openapi"
    )
    result: dict[str, Any] = dict(current)
    result.update(
        {
            "version": 1,
            "cluster": cluster,
            "default_backend": default_backend,
        }
    )
    skip_connect = bool(getattr(setup_panel, "_skip_connect", False))

    if configure_ssh:
        existing_ssh = current.get("ssh", {})
        if not isinstance(existing_ssh, dict):
            existing_ssh = {}
        username = _ask(
            "远端用户名",
            str(existing_ssh.get("username") or ""),
        )
        if not username:
            raise BackendError("SSH 配置需要远端用户名")
        result["ssh"] = {"username": username}
        if skip_connect:
            print("已按 --skip-connect 跳过私钥安装和 SSH 测试。")
        else:
            key_path = str(Path(_ask("私钥文件路径")).expanduser())
            if not key_path:
                raise BackendError("SSH 配置需要私钥路径")
            if not _ask_yes_no("确认写入 ~/.ssh 并测试 SSH 连接？", default=True):
                print("已跳过 SSH 写入；可稍后单独运行 setup-ssh.sh。")
            else:
                _run_setup_ssh(cluster, key_path, username)

    if configure_openapi:
        existing_openapi = current.get("openapi", {})
        if not isinstance(existing_openapi, dict):
            existing_openapi = {}
        if skip_connect:
            region = _ask(
                "区域 ID",
                str(
                    existing_openapi.get("region_id")
                    or profile.get("OPENAPI_REGION_ID")
                    or ""
                ),
            )
            scheduler_id = _ask(
                "调度器 ID（未知可留空）",
                str(existing_openapi.get("scheduler_id") or ""),
            )
            api_username = _ask(
                "区域用户名（未知可留空）",
                str(existing_openapi.get("username") or ""),
            )
            if not region:
                raise BackendError("OpenAPI 配置需要区域 ID")
            result["openapi"] = {
                "region_id": region,
                "scheduler_id": scheduler_id,
                "username": api_username,
            }
            print("已按 --skip-connect 保存 OpenAPI 选择，未验证凭据或区域。")
        else:
            auth_mode = _choose(
                "选择 OpenAPI 认证方式：",
                ["AK/SK（推荐）", "已有区域 token（临时）"],
                1,
            )
            if auth_mode.startswith("AK/SK"):
                api_user = _ask("平台用户名")
                access_key = _ask_secret("AccessKey")
                secret_key = _ask_secret("SecretKey")
                if not api_user or not access_key or not secret_key:
                    raise BackendError("AK/SK 配置不完整")
                backend_instance, previous = _with_openapi_credentials(
                    profile,
                    user=api_user,
                    access_key=access_key,
                    secret_key=secret_key,
                )
            else:
                token_region = _ask(
                    "区域 ID",
                    str(
                        existing_openapi.get("region_id")
                        or profile.get("OPENAPI_REGION_ID")
                        or ""
                    ),
                )
                if not token_region:
                    raise BackendError("使用区域 token 时必须提供区域 ID")
                token = _ask_secret("区域 token")
                if not token:
                    raise BackendError("区域 token 不能为空")
                backend_instance, previous = _with_openapi_credentials(
                    profile, token=token, region_id=token_region
                )
            try:
                regions = [
                    item
                    for item in backend_instance.discover_regions()
                    if str(item.get("clusterId", "")) != "0" and item.get("token")
                ]
                if not regions:
                    raise BackendError("账号没有可用的 OpenAPI 计算区域")
                region_labels = [
                    f"{item.get('clusterName')} ({item.get('clusterId')})"
                    for item in regions
                ]
                existing_region = str(existing_openapi.get("region_id") or "")
                default_region = next(
                    (
                        index
                        for index, item in enumerate(regions, 1)
                        if str(item.get("clusterId")) == existing_region
                    ),
                    1,
                )
                selected_label = _choose(
                    "选择 OpenAPI 区域：", region_labels, default_region
                )
                selected_index = region_labels.index(selected_label)
                region = str(regions[selected_index]["clusterId"])
                discovered = _openapi_probe(backend_instance, region)
            finally:
                _restore_environment(previous)
            result["openapi"] = {
                "region_id": discovered["region_id"],
                "region_name": discovered.get("region_name"),
                "scheduler_id": discovered.get("scheduler_id"),
                "username": discovered.get("username"),
            }
            print(
                f"OpenAPI 验证成功："
                f"{discovered.get('region_name') or discovered['region_id']} "
                f"/ scheduler {discovered['scheduler_id']} "
                f"/ user {discovered['username']}"
            )

    path = save_user_config(result)
    print(f"\n已保存非敏感配置：{path}")
    print("后续可用 `python3 scripts/scnet.py config` 查看。")
    if configure_openapi:
        print("OpenAPI 凭据没有保存；请通过凭据管理器或环境变量注入。")
    print(
        f"下一步：python3 scripts/scnet.py --cluster {shlex.quote(cluster)} doctor"
    )
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
            mode = path.stat().st_mode & 0o777
            add(
                "user_config",
                mode & 0o077 == 0,
                f"{path} mode={mode:03o}",
            )
        else:
            add("user_config", False, f"{path} 不存在；先运行 setup")
    except OSError as exc:
        add("user_config", False, str(exc))

    add(
        "profile",
        bool(profile_name and profile.get("CLUSTER_ID")),
        profile_name or "未选择集群 profile",
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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            add(
                "ssh_config",
                completed.returncode == 0,
                f"alias={alias}"
                if completed.returncode == 0
                else completed.stderr.strip(),
            )
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
        elif not no_network:
            add("ssh_connection", False, "缺少 profile 或 ssh 命令")

    elif backend_name == "openapi":
        has_token = bool(os.environ.get("SCNET_OPENAPI_TOKEN"))
        has_aksk = all(
            os.environ.get(name)
            for name in (
                "SCNET_OPENAPI_USER",
                "SCNET_OPENAPI_ACCESS_KEY",
                "SCNET_OPENAPI_SECRET_KEY",
            )
        )
        add(
            "openapi_credentials",
            has_token or has_aksk,
            "检测到区域 token"
            if has_token
            else ("检测到 AK/SK" if has_aksk else "未检测到 OpenAPI 凭据"),
        )
        openapi_config = user_config.get("openapi", {})
        region = (
            openapi_config.get("region_id")
            if isinstance(openapi_config, dict)
            else None
        )
        add("openapi_region", bool(region), str(region or "未配置区域"))
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
            setup_panel._skip_connect = args.skip_connect
            data = setup_panel()
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
                options["region"] = options.get("region") or openapi_config.get(
                    "region_id"
                )
                options["scheduler_id"] = options.get(
                    "scheduler_id"
                ) or openapi_config.get("scheduler_id")
                options["username"] = options.get("username") or openapi_config.get(
                    "username"
                )
            if args.dry_run:
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
            elif args.operation == "exec":
                options["command"] = " ".join(args.command).strip()
                data = backend.execute(args.operation, options)
            else:
                data = backend.execute(args.operation, options)
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "backend": backend_name,
                        "operation": args.operation,
                        "data": data,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.operation != "setup":
            print(compact_output(args.operation, data))
        if args.operation == "doctor" and not data.get("ok", False):
            return 1
        return 0
    except BackendError as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "operation": args.operation,
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
