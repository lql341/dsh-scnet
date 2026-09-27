#!/usr/bin/env python3
"""Backend-neutral SCNet command-line entrypoint."""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from scnet_backends import BackendContext, BackendError, backend_catalog, create_backend
from scnet_backends.profile import list_profiles, load_profile
from scnet_config import (
    config_path,
    load_user_config,
    redacted_config,
    save_user_config,
)
from scnet_credentials import (
    CredentialError,
    load_openapi_credentials,
    secure_store_name,
    store_openapi_credentials,
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


def _ssh_key_metadata(cluster: str, source: str, username: str) -> dict[str, Any]:
    installed = Path.home() / ".ssh" / f"id_rsa_{cluster}"
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


def setup_panel(mode: str = "all") -> dict[str, Any]:
    profiles = list_profiles(REPO_ROOT)
    if not profiles:
        raise BackendError("clusters/ 下没有 profile")
    current = load_user_config()
    print("\nSCNet HPC 配置/维护面板")
    print("=======================")
    print("自动探测区域、调度器和 SSH 元数据；只要求输入必要凭据。\n")

    current_default = str(current.get("default_backend") or "ssh")
    if mode == "all":
        backend = _choose(
            "选择默认 backend：",
            ["SSH（推荐，支持环境和深度诊断）", "OpenAPI（结构化控制面）"],
            1 if current_default == "ssh" else 2,
        )
        default_backend = "ssh" if backend.startswith("SSH") else "openapi"
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
        profile_names = [item["name"] for item in profiles]
        default_cluster = (
            profile_names.index(selected_cluster) + 1
            if selected_cluster in profile_names
            else 1
        )
        cluster = _choose("选择要配置或更新的 SSH 区域：", profile_names, default_cluster)
        selected_cluster = cluster
        result["cluster"] = cluster
        _, profile = load_profile(REPO_ROOT, cluster)
        existing_ssh = current.get("ssh", {})
        if not isinstance(existing_ssh, dict):
            existing_ssh = {}
        existing_clusters = existing_ssh.get("clusters", {})
        if not isinstance(existing_clusters, dict):
            existing_clusters = {}
        existing_profile = existing_clusters.get(cluster, {})
        if not isinstance(existing_profile, dict):
            existing_profile = {}
        key_path = ""
        if not skip_connect:
            key_path = str(Path(_ask("私钥文件路径")).expanduser())
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
        clusters = dict(existing_clusters)
        clusters[cluster] = {**existing_profile, "username": username}
        result["ssh"] = {"clusters": clusters}
        if skip_connect:
            print("已按 --skip-connect 跳过私钥安装和 SSH 测试。")
        else:
            if not _ask_yes_no("确认安装/轮换私钥并测试连接？", default=True):
                print("已跳过 SSH 写入；可稍后单独运行 setup-ssh.sh。")
            else:
                _run_setup_ssh(cluster, key_path, username)
                clusters[cluster] = _ssh_key_metadata(
                    cluster, key_path, username
                )

    if configure_openapi:
        existing_openapi = current.get("openapi", {})
        if not isinstance(existing_openapi, dict):
            existing_openapi = {}
        if skip_connect:
            print("已按 --skip-connect 跳过 OpenAPI 认证和区域发现。")
        else:
            saved_credentials, saved_provider = load_openapi_credentials()
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
                api_user = _ask(
                    "平台用户名",
                    str(existing_openapi.get("platform_user") or ""),
                )
                access_key = _ask_secret("AccessKey")
                secret_key = _ask_secret("SecretKey")
                if not api_user or not access_key or not secret_key:
                    raise BackendError("AK/SK 配置不完整")
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
                print("\n已自动发现授权区域：")
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
                existing_region = str(
                    existing_openapi.get("default_region_id")
                    or existing_openapi.get("region_id")
                    or ""
                )
                default_region = next(
                    (
                        index
                        for index, item in enumerate(contexts, 1)
                        if item["region_id"] == existing_region
                    ),
                    1,
                )
                selected_label = _choose(
                    "选择 OpenAPI 区域：", region_labels, default_region
                )
                selected_index = region_labels.index(selected_label)
                selected = contexts[selected_index]
            finally:
                _restore_environment(previous)
            stored_provider = saved_provider
            if entered_credentials and secure_store_name():
                if _ask_yes_no(
                    f"是否将 AK/SK 保存到 {secure_store_name()}？",
                    default=True,
                ):
                    try:
                        provider = store_openapi_credentials(
                            api_user, access_key, secret_key
                        )
                        stored_provider = provider
                        print(f"OpenAPI 凭据已保存到 {provider}。")
                    except CredentialError as exc:
                        print(f"无法保存到安全凭据库：{exc}")
            selected_schedulers = selected.get("schedulers") or []
            default_scheduler = (
                selected_schedulers[0].get("id")
                if len(selected_schedulers) == 1
                else ""
            )
            result["openapi"] = {
                "platform_user": api_user,
                "credential_provider": stored_provider,
                "default_region_id": selected["region_id"],
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
                f"默认 OpenAPI 区域："
                f"{selected.get('name') or selected['region_id']}"
            )

    if selected_cluster:
        result["cluster"] = selected_cluster
    path = save_user_config(result)
    print(f"\n已保存非敏感配置：{path}")
    print("后续可用 `python3 scripts/scnet.py config` 查看。")
    if configure_openapi and not secure_store_name():
        print("系统没有可用安全凭据库；请通过环境变量注入 AK/SK。")
    doctor_cluster = selected_cluster or str(current.get("cluster") or "")
    suffix = f" --cluster {shlex.quote(doctor_cluster)}" if doctor_cluster else ""
    print(f"下一步：python3 scripts/scnet.py{suffix} doctor")
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
        credentials, credential_provider = load_openapi_credentials()
        has_aksk = bool(credentials)
        add(
            "openapi_credentials",
            has_token or has_aksk,
            "检测到区域 token"
            if has_token
            else (
                f"检测到 AK/SK（{credential_provider}）"
                if has_aksk
                else "未检测到 OpenAPI 凭据"
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
            data = setup_panel(args.mode)
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
                region = (
                    options.get("region")
                    or openapi_config.get("default_region_id")
                    or openapi_config.get("region_id")
                )
                options["region"] = region
                region_config: dict[str, Any] = {}
                regions = openapi_config.get("regions")
                if isinstance(regions, dict) and region:
                    candidate = regions.get(str(region))
                    if isinstance(candidate, dict):
                        region_config = candidate
                scheduler_id = (
                    options.get("scheduler_id")
                    or openapi_config.get("scheduler_id")
                )
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
                    or openapi_config.get("username")
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
