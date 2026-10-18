"""Secure OpenAPI credential discovery and storage."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from typing import Any


SERVICE = "scnet-hpc-openapi"


class CredentialError(RuntimeError):
    """A user-facing credential-store failure."""


def _credential_command(command: list[str], **options: Any) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, timeout=30, **options)
    except (OSError, subprocess.TimeoutExpired):
        # TimeoutExpired includes argv, which contains the Keychain payload.
        raise CredentialError("系统凭据操作失败或超时；请检查密钥环服务及解锁状态后重试。") from None


def normalize_credential(value: str, label: str) -> str:
    """Accept surrounding paste quotes, but never echo a credential in an error."""
    value = value.strip().lstrip("\ufeff")
    if len(value) >= 2 and (value[0], value[-1]) in {
        ('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")
    }:
        value = value[1:-1].strip()
    if not value:
        raise CredentialError(f"{label} 不能为空，请只粘贴对应字段的值。")
    if re.match(r"(?i)^(export\s|\$env:|SCNET_OPENAPI_|(?:AccessKey|SecretKey)\s*[:=])", value):
        raise CredentialError(f"{label} 收到了变量赋值或字段名；请只粘贴值，不要粘贴整行命令。")
    if any(character.isspace() or ord(character) < 32 or character in "\u200b\ufeff\u200e\u200f" for character in value):
        raise CredentialError(f"{label} 含空白、换行或不可见字符，请重新复制单个字段。")
    return value


def _windows_credential(action: str, payload: str = "", user: str = "") -> str | bool | None:
    """Use the current Windows user's Generic Credential store, without extra packages."""
    import ctypes
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    pointer = ctypes.POINTER(Credential)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [pointer, wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None

    if action == "read":
        item = pointer()
        success = api.CredReadW(SERVICE, 1, 0, ctypes.byref(item))
        if success:
            try:
                return ctypes.string_at(item.contents.CredentialBlob, item.contents.CredentialBlobSize).decode("utf-8")
            except UnicodeDecodeError:
                raise CredentialError(
                    "Windows 中已保存的 OpenAPI 凭据编码无效；请运行 setup modify --mode openapi 重新配置，"
                    "或在凭据管理器删除 scnet-hpc-openapi 条目后重试。"
                ) from None
            finally:
                api.CredFree(item)
    elif action == "write":
        encoded = payload.encode("utf-8")
        if len(encoded) > 2560:
            raise CredentialError("凭据超出 Windows 凭据管理器容量，请检查是否粘贴了整个文件。")
        buffer = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        item = Credential()
        item.Type, item.TargetName, item.UserName = 1, SERVICE, user
        item.CredentialBlobSize, item.CredentialBlob = len(encoded), buffer
        item.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE: same user, across logon sessions.
        success = api.CredWriteW(ctypes.byref(item), 0)
    elif action == "delete":
        success = api.CredDeleteW(SERVICE, 1, 0)
    else:
        raise ValueError("unknown credential operation")
    if success:
        return True
    error = ctypes.get_last_error()
    if error == 1168 and action in {"read", "delete"}:
        return None
    raise CredentialError(
        f"Windows 凭据管理器{action}失败（错误码 {error}）；"
        "请在已登录的桌面用户会话运行，或使用环境变量注入。"
    )


def _valid(data: Any) -> bool:
    return isinstance(data, dict) and all(
        isinstance(data.get(key), str) and data[key]
        for key in ("user", "access_key", "secret_key")
    )


def environment_credentials() -> dict[str, str] | None:
    data = {
        "user": os.environ.get("SCNET_OPENAPI_USER", ""),
        "access_key": os.environ.get("SCNET_OPENAPI_ACCESS_KEY", ""),
        "secret_key": os.environ.get("SCNET_OPENAPI_SECRET_KEY", ""),
    }
    if not any(data.values()):
        return None
    missing = [name for name, value in data.items() if not value]
    if missing:
        raise CredentialError("OpenAPI 环境变量不完整；请同时设置 USER、ACCESS_KEY、SECRET_KEY，或清除这组三个变量后使用系统凭据库。")
    return {key: normalize_credential(value, key) for key, value in data.items()}


def secure_store_name() -> str | None:
    if platform.system() == "Windows":
        return "Windows Credential Manager"
    if platform.system() == "Darwin" and shutil.which("security"):
        return "macOS Keychain"
    if shutil.which("secret-tool"):
        return "Secret Service"
    return None


def load_secure_credentials() -> dict[str, str] | None:
    provider = secure_store_name()
    if provider == "Windows Credential Manager":
        payload = _windows_credential("read")
        if payload is None:
            return None
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            raise CredentialError("Windows 中已保存的 OpenAPI 凭据格式无效，请运行 setup modify --mode openapi 重新配置。") from None
        return data if _valid(data) else None
    if provider == "macOS Keychain":
        command = ["security", "find-generic-password", "-s", SERVICE, "-w"]
    elif provider == "Secret Service":
        command = ["secret-tool", "lookup", "service", SERVICE]
    else:
        return None
    try:
        completed = subprocess.run(
            command, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CredentialError(f"无法读取 {provider}；请检查密钥环服务是否运行并已解锁。") from None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return data if _valid(data) else None


def load_openapi_credentials() -> tuple[dict[str, str] | None, str | None]:
    data = environment_credentials()
    if data:
        return data, "environment"
    data = load_secure_credentials()
    if data:
        return data, secure_store_name()
    return None, None


def store_openapi_credentials(
    user: str, access_key: str, secret_key: str
) -> str:
    data = {
        "user": normalize_credential(user, "平台用户名"),
        "access_key": normalize_credential(access_key, "AccessKey"),
        "secret_key": normalize_credential(secret_key, "SecretKey"),
    }
    if not _valid(data):
        raise CredentialError("OpenAPI credentials are incomplete")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    provider = secure_store_name()
    if provider == "Windows Credential Manager":
        _windows_credential("write", payload, data["user"])
        return provider
    if provider == "macOS Keychain":
        command = [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            SERVICE,
            "-a",
            user,
            "-w",
            payload,
        ]
        completed = _credential_command(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    elif provider == "Secret Service":
        command = [
            "secret-tool",
            "store",
            "--label=SCNet OpenAPI",
            "service",
            SERVICE,
            "user",
            user,
        ]
        completed = _credential_command(
            command,
            input=payload,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    else:
        raise CredentialError(
            "no supported secure store; use SCNET_OPENAPI_USER, "
            "SCNET_OPENAPI_ACCESS_KEY, and SCNET_OPENAPI_SECRET_KEY"
        )
    if completed.returncode != 0:
        raise CredentialError(
            f"无法写入 {provider}（exit={completed.returncode}）；请检查密钥环服务及解锁状态。"
        )
    return str(provider)


def delete_openapi_credentials() -> tuple[bool, str | None]:
    provider = secure_store_name()
    if provider == "Windows Credential Manager":
        return bool(_windows_credential("delete")), provider
    if provider == "macOS Keychain":
        command = ["security", "delete-generic-password", "-s", SERVICE]
    elif provider == "Secret Service":
        command = ["secret-tool", "clear", "service", SERVICE]
    else:
        return False, None
    completed = _credential_command(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return True, provider
    if load_secure_credentials() is None:
        return False, provider
    raise CredentialError(
        f"无法清除 {provider}（exit={completed.returncode}），请检查解锁状态。"
    )
