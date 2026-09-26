"""SCNet OpenAPI 2.0 backend using only the Python standard library."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .base import Backend, BackendError, require_option


STATUS_MAP = {
    "statR": "RUNNING",
    "statQ": "PENDING",
    "statH": "HELD",
    "statS": "SUSPENDED",
    "statE": "EXITING",
    "statC": "COMPLETED",
    "statW": "WAITING",
    "statX": "OTHER",
}
WALLTIME_RE = re.compile(r"^(?:[0-9]+-)?[0-9]{1,3}:[0-9]{2}:[0-9]{2}$")


def _bounded_int(options: Mapping[str, Any], name: str, minimum: int) -> int:
    try:
        value = int(options.get(name) if options.get(name) is not None else minimum)
    except (TypeError, ValueError) as exc:
        raise BackendError(f"{name} must be an integer") from exc
    if value < minimum:
        raise BackendError(f"{name} must be >= {minimum}")
    return value


def canonical_signature(access_key: str, timestamp: str, user: str, secret_key: str) -> str:
    message = json.dumps(
        {"accessKey": access_key, "timestamp": timestamp, "user": user},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def service_endpoint(base_url: str, service: str, suffix: str) -> str:
    """Join endpoints whether the discovered URL already ends in /hpc or /efile."""
    split = urlsplit(base_url.rstrip("/"))
    path = split.path.rstrip("/")
    service_part = f"/{service}"
    if not path.endswith(service_part):
        path += service_part
    path += "/" + suffix.lstrip("/")
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


def normalize_job(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_state = item.get("jobStatus") or item.get("state") or ""
    return {
        "job_id": str(item.get("jobId") or item.get("job_id") or ""),
        "name": item.get("jobName") or item.get("name"),
        "state": STATUS_MAP.get(str(raw_state), raw_state),
        "raw_state": raw_state,
        "queue": item.get("queue"),
        "user": item.get("user"),
        "nodes": item.get("nodeNumReq") or item.get("nodeUsed"),
        "cpus": item.get("procNumReq") or item.get("procNumUsed"),
        "gpus": item.get("gpuNumReq") or item.get("gpuNumUsed"),
        "dcus": item.get("dcuNumReq") or item.get("dcuNumUsed"),
        "elapsed": item.get("jobRunTime"),
        "submitted_at": item.get("jobSubmitTime"),
        "started_at": item.get("jobStartTime"),
        "ended_at": item.get("jobEndTime"),
        "exit_code": item.get("exitCode"),
        "reason": item.get("reason"),
        "work_dir": item.get("workDir"),
        "stdout": item.get("outputPath"),
        "stderr": item.get("errorPath"),
    }


class OpenAPIBackend(Backend):
    name = "openapi"
    capabilities = frozenset(
        {
            "clusters",
            "queues",
            "limits",
            "job",
            "logs",
            "submit",
            "cancel",
            "files",
            "mkdir",
            "upload",
            "download",
        }
    )

    def _env(self, name: str, default: str | None = None) -> str | None:
        value = os.environ.get(name)
        return value if value not in (None, "") else default

    def _json_request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        json_body: Any | None = None,
        form: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "scnet-hpc/1",
        }
        if headers:
            request_headers.update(headers)
        if token:
            request_headers["token"] = token
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urlencode(form).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, method=method, headers=request_headers)
        try:
            with urlopen(request, timeout=self.context.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise BackendError(f"HTTP {exc.code} from SCNet OpenAPI: {detail[:500]}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise BackendError(f"SCNet OpenAPI request failed: {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendError("SCNet OpenAPI returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise BackendError("SCNet OpenAPI response must be a JSON object")
        code = str(payload.get("code", ""))
        if code != "0":
            message = payload.get("msg") or "unknown OpenAPI error"
            raise BackendError(f"SCNet OpenAPI error {code}: {message}")
        return payload.get("data")

    def _regions(self) -> list[dict[str, Any]]:
        direct_token = self._env("SCNET_OPENAPI_TOKEN")
        if direct_token:
            region_id = (
                self._env("SCNET_OPENAPI_REGION_ID")
                or self.context.profile.get("OPENAPI_REGION_ID")
                or ""
            )
            return [
                {
                    "clusterId": region_id,
                    "clusterName": self._env("SCNET_OPENAPI_REGION_NAME", "configured"),
                    "token": direct_token,
                }
            ]

        user = self._env("SCNET_OPENAPI_USER")
        access_key = self._env("SCNET_OPENAPI_ACCESS_KEY")
        secret_key = self._env("SCNET_OPENAPI_SECRET_KEY")
        missing = [
            name
            for name, value in (
                ("SCNET_OPENAPI_USER", user),
                ("SCNET_OPENAPI_ACCESS_KEY", access_key),
                ("SCNET_OPENAPI_SECRET_KEY", secret_key),
            )
            if not value
        ]
        if missing:
            raise BackendError(
                "OpenAPI credentials are not configured; set " + ", ".join(missing)
            )
        timestamp = str(int(time.time()))
        signature = canonical_signature(access_key, timestamp, user, secret_key)
        auth_base = self._env("SCNET_OPENAPI_AUTH_BASE", "https://api.scnet.cn")
        url = auth_base.rstrip("/") + "/api/user/v3/tokens"
        data = self._json_request(
            "POST",
            url,
            headers={
                "user": user,
                "accessKey": access_key,
                "signature": signature,
                "timestamp": timestamp,
            },
        )
        if not isinstance(data, list):
            raise BackendError("token endpoint returned an unexpected data shape")
        return [item for item in data if isinstance(item, dict)]

    def _select_region(
        self, options: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        regions = self._regions()
        requested = (
            options.get("region")
            or self.context.profile.get("OPENAPI_REGION_ID")
            or self._env("SCNET_OPENAPI_REGION_ID")
        )
        usable = [
            item
            for item in regions
            if str(item.get("clusterId", "")) != "0" and item.get("token")
        ]
        if requested:
            for item in usable:
                if str(item.get("clusterId")) == str(requested) or item.get(
                    "clusterName"
                ) == requested:
                    return item, regions
            raise BackendError(f"OpenAPI region {requested!r} is not available")
        if len(usable) == 1:
            return usable[0], regions
        names = ", ".join(
            f"{item.get('clusterName')}({item.get('clusterId')})" for item in usable
        )
        raise BackendError(
            "multiple OpenAPI regions are available; select one with --region: " + names
        )

    def _center(
        self, options: Mapping[str, Any]
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        region, _ = self._select_region(options)
        token = str(region["token"])
        center_url = self._env(
            "SCNET_OPENAPI_CENTER_URL",
            "https://www.scnet.cn/ac/openapi/v2/center",
        )
        data = self._json_request("GET", center_url, token=token)
        if not isinstance(data, dict):
            raise BackendError("center endpoint returned an unexpected data shape")
        return data, token, region

    @staticmethod
    def _enabled_url(center: Mapping[str, Any], field: str) -> str:
        values = center.get(field)
        if not isinstance(values, list):
            raise BackendError(f"center response has no {field}")
        for item in values:
            if not isinstance(item, dict):
                continue
            enabled = str(item.get("enable", "true")).lower() == "true"
            if enabled and item.get("url"):
                return str(item["url"])
        raise BackendError(f"center response has no enabled URL in {field}")

    def _hpc_context(
        self, options: Mapping[str, Any]
    ) -> tuple[str, str, str, str, dict[str, Any]]:
        center, token, region = self._center(options)
        hpc_url = self._enabled_url(center, "hpcUrls")
        schedulers = self._json_request(
            "GET",
            service_endpoint(hpc_url, "hpc", "/openapi/v2/cluster"),
            token=token,
        )
        if not isinstance(schedulers, list):
            raise BackendError("cluster endpoint returned an unexpected data shape")
        requested = (
            options.get("scheduler_id")
            or self.context.profile.get("OPENAPI_SCHEDULER_ID")
            or self._env("SCNET_OPENAPI_SCHEDULER_ID")
        )
        selected: Mapping[str, Any] | None = None
        if requested:
            selected = next(
                (item for item in schedulers if str(item.get("id")) == str(requested)),
                None,
            )
            if selected is None:
                raise BackendError(f"scheduler {requested!r} is not available")
        elif len(schedulers) == 1:
            selected = schedulers[0]
        else:
            available = ", ".join(
                f"{item.get('text')}({item.get('id')})" for item in schedulers
            )
            raise BackendError(
                "multiple schedulers are available; use --scheduler-id: " + available
            )
        user_info = center.get("clusterUserInfo") or {}
        username = (
            options.get("username")
            or self.context.profile.get("OPENAPI_USERNAME")
            or self._env("SCNET_OPENAPI_USERNAME")
            or user_info.get("userName")
        )
        if not username:
            raise BackendError("OpenAPI username is missing from center response")
        return hpc_url, token, str(selected["id"]), str(username), region

    def _efile_context(
        self, options: Mapping[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        center, token, region = self._center(options)
        return self._enabled_url(center, "efileUrls"), token, region

    def discover_regions(self) -> list[dict[str, Any]]:
        """Return authorized regions for setup and diagnostics."""
        return self._regions()

    def discover_region_context(self, region: str) -> dict[str, Any]:
        """Resolve the selected region's scheduler and user without submitting work."""
        _, _, selected = self._center({"region": region})
        _, _, scheduler_id, username, _ = self._hpc_context({"region": region})
        return {
            "region_id": str(selected.get("clusterId") or region),
            "region_name": selected.get("clusterName"),
            "scheduler_id": scheduler_id,
            "username": username,
        }

    def op_clusters(self, options: Mapping[str, Any]) -> Any:
        regions = self._regions()
        result = [
            {
                "region_id": str(item.get("clusterId", "")),
                "name": item.get("clusterName"),
                "available": bool(item.get("token")),
            }
            for item in regions
            if str(item.get("clusterId", "")) != "0"
        ]
        if options.get("raw"):
            safe_raw = [
                {
                    **item,
                    "token": "<redacted>",
                }
                for item in regions
            ]
            return {"items": result, "raw": safe_raw}
        return result

    def op_queues(self, options: Mapping[str, Any]) -> Any:
        hpc_url, token, scheduler_id, username, _ = self._hpc_context(options)
        params = urlencode({"strJobManagerID": scheduler_id})
        url = service_endpoint(
            hpc_url,
            "hpc",
            f"/openapi/v2/queuenames/users/{quote(username)}?{params}",
        )
        data = self._json_request("GET", url, token=token)
        result = []
        for item in data or []:
            result.append(
                {
                    "partition": item.get("queueName") or item.get("id"),
                    "nodes": item.get("queNodes"),
                    "free_nodes": item.get("queFreeNodes"),
                    "cpus": item.get("queNcpus"),
                    "free_cpus": item.get("queFreeNcpus"),
                    "max_cpus": item.get("queMaxNcpus"),
                    "max_cpus_per_node": item.get("queMaxPPN"),
                    "max_nodes": item.get("queMaxNodect"),
                    "max_walltime": item.get("queMaxWalltime"),
                    "max_gpus_per_node": item.get("queMaxGpuPN"),
                    "max_dcus_per_node": item.get("queMaxDcuPN"),
                    "charge_rate": item.get("queChargeRate"),
                }
            )
        return {"items": result, "raw": data} if options.get("raw") else result

    def op_limits(self, options: Mapping[str, Any]) -> Any:
        hpc_url, token, scheduler_id, _, _ = self._hpc_context(options)
        params = urlencode({"strJobManagerID": scheduler_id})
        data = self._json_request(
            "GET",
            service_endpoint(
                hpc_url, "hpc", f"/openapi/v2/userquotas/userlimit?{params}"
            ),
            token=token,
        )
        if not isinstance(data, dict):
            return data
        key_map = {
            "userMaxCpu": "user_max_cpus",
            "userMaxDcu": "user_max_dcus",
            "userMaxGpu": "user_max_gpus",
            "userMaxMlu": "user_max_mlus",
            "userMaxMem": "user_max_memory_mb",
            "userMaxNode": "user_max_nodes",
            "userMaxSubmitJob": "user_max_submitted_jobs",
            "userMaxRunJob": "user_max_running_jobs",
            "accountMaxCpu": "account_max_cpus",
            "accountMaxDcu": "account_max_dcus",
            "accountMaxGpu": "account_max_gpus",
            "accountMaxNode": "account_max_nodes",
            "maxWallTime": "remaining_machine_time_seconds",
        }
        result = {target: data.get(source) for source, target in key_map.items()}
        return {"data": result, "raw": data} if options.get("raw") else result

    def op_job(self, options: Mapping[str, Any]) -> Any:
        job_id = str(require_option(options, "job_id"))
        hpc_url, token, _, _, _ = self._hpc_context(options)
        data = self._json_request(
            "GET",
            service_endpoint(hpc_url, "hpc", f"/openapi/v2/jobs/{quote(job_id)}"),
            token=token,
        )
        if not isinstance(data, dict):
            raise BackendError("job endpoint returned an unexpected data shape")
        result = normalize_job(data)
        if options.get("raw"):
            result["raw"] = data
        return result

    def op_logs(self, options: Mapping[str, Any]) -> Any:
        path = str(require_option(options, "path"))
        if not path.startswith("/"):
            raise BackendError("OpenAPI log path must be absolute")
        hpc_url, token, _, _, _ = self._hpc_context(options)
        direction = options.get("direction") or "tail"
        roll = "UP" if direction == "tail" else "DOWN"
        page = int(options.get("page") or 1)
        data = self._json_request(
            "POST",
            service_endpoint(hpc_url, "hpc", "/openapi/v2/file/content"),
            token=token,
            form={
                "hostName": options.get("host_name") or "",
                "dirPath": path,
                "triggerNum": page,
                "rollDirection": roll,
            },
        )
        if not isinstance(data, dict):
            raise BackendError("log endpoint returned an unexpected data shape")
        lines = str(data.get("data") or "").splitlines()
        requested_lines = int(options.get("lines") or 200)
        if direction == "tail":
            lines = lines[-requested_lines:]
        else:
            lines = lines[:requested_lines]
        result = {
            "path": path,
            "direction": direction,
            "page": page,
            "total_pages": data.get("totalTriggerTimes"),
            "total_lines": data.get("allLineTotal"),
            "lines": lines,
        }
        return {"data": result, "raw": data} if options.get("raw") else result

    def _submit_payload(self, options: Mapping[str, Any]) -> dict[str, Any]:
        name = str(require_option(options, "name"))
        command = str(require_option(options, "command"))
        work_dir = str(require_option(options, "work_dir"))
        queue = str(require_option(options, "queue"))
        if not work_dir.startswith("/"):
            raise BackendError("OpenAPI work directory must be absolute")
        if any(char in name for char in "\r\n") or any(
            char in queue for char in "\r\n"
        ):
            raise BackendError("job name and queue must not contain newlines")
        nodes = _bounded_int(options, "nodes", 1)
        cpus = _bounded_int(options, "cpus", 1)
        gpus = _bounded_int(options, "gpus", 0)
        dcus = _bounded_int(options, "dcus", 0)
        walltime = str(options.get("walltime") or "24:00:00")
        if not WALLTIME_RE.fullmatch(walltime):
            raise BackendError("walltime must use HH:MM:SS or D-HH:MM:SS")
        scheduler_options = options.get("scheduler_options") or []
        if not isinstance(scheduler_options, (list, tuple)):
            raise BackendError("scheduler_options must be a list")
        return {
            "name": name,
            "command": command,
            "work_dir": work_dir,
            "queue": queue,
            "nodes": nodes,
            "cpus": cpus,
            "gpus": gpus,
            "dcus": dcus,
            "memory": str(options.get("memory") or ""),
            "walltime": walltime,
            "exclusive": bool(options.get("exclusive")),
            "stdout": options.get("stdout")
            or f"{work_dir.rstrip('/')}/std.out.%j",
            "stderr": options.get("stderr")
            or f"{work_dir.rstrip('/')}/std.err.%j",
            "scheduler_options": list(scheduler_options),
        }

    def _submit_request(self, options: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
        payload = self._submit_payload(options)
        hpc_url, token, scheduler_id, _, region = self._hpc_context(options)
        job_info = {
            "GAP_CMD_FILE": payload["command"],
            "GAP_NNODE": str(payload["nodes"]),
            "GAP_NODE_STRING": options.get("node_string") or "",
            "GAP_SUBMIT_TYPE": "cmd",
            "GAP_JOB_NAME": payload["name"],
            "GAP_WORK_DIR": payload["work_dir"],
            "GAP_QUEUE": payload["queue"],
            "GAP_NPROC": str(payload["cpus"]),
            "GAP_PPN": "",
            "GAP_NGPU": str(payload["gpus"] or ""),
            "GAP_NDCU": str(payload["dcus"] or ""),
            "GAP_JOB_MEM": payload["memory"],
            "GAP_WALL_TIME": payload["walltime"],
            "GAP_EXCLUSIVE": "1" if payload["exclusive"] else "",
            "GAP_APPNAME": "BASE",
            "GAP_MULTI_SUB": "",
            "GAP_STD_OUT_FILE": payload["stdout"],
            "GAP_STD_ERR_FILE": payload["stderr"],
            "GAP_SCHEDULER_OPT_WEB": "\n".join(payload["scheduler_options"]),
            "GAP_CLUSTER_ID": str(region.get("clusterId") or ""),
        }
        return hpc_url, token, {
            "strJobManagerID": scheduler_id,
            "mapAppJobInfo": job_info,
        }

    def preview_submit(self, options: Mapping[str, Any]) -> Any:
        payload = self._submit_payload(options)
        return {
            "backend": self.name,
            "operation": "submit",
            "requires_network_resolution": True,
            "request": payload,
            "note": "scheduler and region IDs will be resolved before POST; no request sent",
        }

    def op_submit(self, options: Mapping[str, Any]) -> Any:
        hpc_url, token, body = self._submit_request(options)
        data = self._json_request(
            "POST",
            service_endpoint(
                hpc_url, "hpc", "/openapi/v2/apptemplates/BASIC/BASE/job"
            ),
            token=token,
            json_body=body,
        )
        result = {"job_id": str(data)}
        return {"data": result, "raw": data} if options.get("raw") else result

    def op_cancel(self, options: Mapping[str, Any]) -> Any:
        job_id = str(require_option(options, "job_id"))
        hpc_url, token, scheduler_id, username, _ = self._hpc_context(options)
        method = self._env("SCNET_OPENAPI_CANCEL_METHOD", "5")
        data = self._json_request(
            "DELETE",
            service_endpoint(hpc_url, "hpc", "/openapi/v2/jobs"),
            token=token,
            form={
                "jobMethod": method,
                "strJobInfoMap": f"{scheduler_id},{username}:{job_id}:",
            },
        )
        return {"job_id": job_id, "cancelled": True, "result": data}

    def preview_cancel(self, options: Mapping[str, Any]) -> Any:
        job_id = str(require_option(options, "job_id"))
        return {
            "backend": self.name,
            "operation": "cancel",
            "job_id": job_id,
            "note": "no DELETE request sent",
        }

    def op_mkdir(self, options: Mapping[str, Any]) -> Any:
        path = str(require_option(options, "path"))
        if (
            not path.startswith("/")
            or "\n" in path
            or "\r" in path
            or "\x00" in path
        ):
            raise BackendError("directory path must be a safe absolute path")
        efile_url, token, _ = self._efile_context(options)
        url = (
            service_endpoint(efile_url, "efile", "/openapi/v2/file/mkdir")
            + "?"
            + urlencode(
                {
                    "path": path,
                    "createParents": "true" if options.get("parents", False) else "false",
                }
            )
        )
        data = self._json_request("POST", url, token=token, json_body={})
        result = {"path": path, "created": True}
        return {"data": result, "raw": data} if options.get("raw") else result

    def preview_mkdir(self, options: Mapping[str, Any]) -> Any:
        path = str(require_option(options, "path"))
        if not path.startswith("/"):
            raise BackendError("directory path must be absolute")
        return {
            "backend": self.name,
            "operation": "mkdir",
            "path": path,
            "parents": bool(options.get("parents", False)),
            "note": "no POST request sent",
        }

    def op_files(self, options: Mapping[str, Any]) -> Any:
        efile_url, token, _ = self._efile_context(options)
        limit = _bounded_int(options, "limit", 1)
        start = _bounded_int(options, "start", 0)
        params = {
            "limit": limit,
            "start": start,
            "order": options.get("order") or "asc",
            "orderBy": options.get("order_by") or "name",
        }
        if options.get("path"):
            params["path"] = options["path"]
        data = self._json_request(
            "GET",
            service_endpoint(
                efile_url, "efile", "/openapi/v2/file/list"
            )
            + "?"
            + urlencode(params),
            token=token,
        )
        if not isinstance(data, dict):
            return data
        result = {
            "path": data.get("path"),
            "total": data.get("total"),
            "files": [
                {
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "size": item.get("size"),
                    "directory": item.get("isDirectory"),
                    "modified_at": item.get("lastModifiedTime"),
                    "permission": item.get("permission"),
                }
                for item in data.get("fileList") or []
            ],
        }
        return {"data": result, "raw": data} if options.get("raw") else result

    def op_upload(self, options: Mapping[str, Any]) -> Any:
        local_path = Path(str(require_option(options, "local_path"))).expanduser()
        remote_path = str(require_option(options, "remote_path"))
        if not local_path.is_file():
            raise BackendError(f"local file does not exist: {local_path}")
        if (
            not remote_path.startswith("/")
            or "\n" in remote_path
            or "\r" in remote_path
            or "\x00" in remote_path
        ):
            raise BackendError("remote upload directory must be absolute")
        chunk_size = int(options.get("chunk_size") or 0)
        if chunk_size < 0:
            raise BackendError("chunk size must be non-negative")
        if chunk_size and chunk_size < 1024 * 1024:
            raise BackendError("chunk size must be at least 1 MiB or 0")
        if chunk_size and local_path.stat().st_size > chunk_size:
            return self._op_chunked_upload(local_path, remote_path, options, chunk_size)
        efile_url, token, _ = self._efile_context(options)
        content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        self._multipart_request(
            service_endpoint(efile_url, "efile", "/openapi/v2/file/upload"),
            token,
            {
                "cover": "cover" if options.get("cover") else "uncover",
                "path": remote_path,
            },
            local_path.name,
            local_path.read_bytes(),
            content_type,
        )
        return {"local_path": str(local_path), "remote_path": remote_path}

    def _multipart_request(
        self,
        url: str,
        token: str,
        fields: Mapping[str, Any],
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> Any:
        boundary = "----scnet-hpc-" + uuid.uuid4().hex
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        safe_name = file_name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + file_bytes
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        request = Request(
            url,
            data=b"".join(parts),
            method="POST",
            headers={
                "token": token,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
                "User-Agent": "scnet-hpc/1",
            },
        )
        try:
            with urlopen(request, timeout=self.context.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            raise BackendError(f"OpenAPI multipart upload failed: {exc}") from exc
        if not isinstance(payload, dict) or str(payload.get("code", "")) != "0":
            raise BackendError(
                f"SCNet OpenAPI error {payload.get('code')}: {payload.get('msg')}"
            )
        return payload.get("data")

    def _op_chunked_upload(
        self,
        local_path: Path,
        remote_path: str,
        options: Mapping[str, Any],
        chunk_size: int,
    ) -> dict[str, Any]:
        efile_url, token, _ = self._efile_context(options)
        total_size = local_path.stat().st_size
        total_chunks = max(1, (total_size + chunk_size - 1) // chunk_size)
        filename = local_path.name
        relative_path = str(options.get("relative_path") or filename)
        cover = "cover" if options.get("cover") else "uncover"
        identifier = str(options.get("identifier") or f"{total_size}-{filename}")
        endpoint = service_endpoint(efile_url, "efile", "/openapi/v2/file/burst")
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with local_path.open("rb") as stream:
            for chunk_number in range(1, total_chunks + 1):
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                self._multipart_request(
                    endpoint,
                    token,
                    {
                        "chunkNumber": chunk_number,
                        "cover": cover,
                        "filename": filename,
                        "identifier": identifier,
                        "path": remote_path,
                        "relativePath": relative_path,
                        "totalChunks": total_chunks,
                        "totalSize": total_size,
                        "chunkSize": chunk_size,
                        "currentChunkSize": len(chunk),
                    },
                    filename,
                    chunk,
                    content_type,
                )
        merge_data = self._json_request(
            "POST",
            service_endpoint(efile_url, "efile", "/openapi/v2/file/merge"),
            token=token,
            form={
                "cover": cover,
                "filename": filename,
                "id": "",
                "identifier": identifier,
                "path": remote_path,
                "relativePath": relative_path,
            },
        )
        result = {
            "local_path": str(local_path),
            "remote_path": remote_path,
            "bytes": total_size,
            "chunks": total_chunks,
        }
        return {"data": result, "raw": merge_data} if options.get("raw") else result

    def op_download(self, options: Mapping[str, Any]) -> Any:
        remote_path = str(require_option(options, "remote_path"))
        local_path = Path(str(require_option(options, "local_path"))).expanduser()
        if (
            not remote_path.startswith("/")
            or "\n" in remote_path
            or "\r" in remote_path
            or "\x00" in remote_path
        ):
            raise BackendError("remote download path must be absolute")
        if local_path.exists() and not options.get("cover"):
            raise BackendError("local path already exists; pass --cover to overwrite it")
        efile_url, token, _ = self._efile_context(options)
        url = (
            service_endpoint(efile_url, "efile", "/openapi/v2/file/download")
            + "?"
            + urlencode({"path": remote_path})
        )
        request = Request(
            url,
            method="GET",
            headers={"token": token, "User-Agent": "scnet-hpc/1"},
        )
        try:
            with urlopen(request, timeout=self.context.timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                content = response.read()
        except (HTTPError, URLError, OSError) as exc:
            raise BackendError(f"OpenAPI download failed: {exc}") from exc
        if "application/json" in content_type:
            try:
                payload = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and str(payload.get("code", "0")) != "0":
                raise BackendError(
                    f"SCNet OpenAPI error {payload.get('code')}: {payload.get('msg')}"
                )
        local_path.write_bytes(content)
        return {
            "remote_path": remote_path,
            "local_path": str(local_path),
            "bytes": len(content),
        }
