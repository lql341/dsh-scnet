"""SCNet OpenAPI 2.0 backend using only the Python standard library."""

from __future__ import annotations

import json
import mimetypes
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .base import Backend, BackendError, require_option
from scnet_sdk.client import (
    SCNetClient,
    canonical_signature,
    service_endpoint,
)


STATUS_MAP = {
    "statR": "RUNNING",
    "statQ": "PENDING",
    "statH": "HELD",
    "statS": "SUSPENDED",
    "statE": "EXITING",
    "statC": "COMPLETED",
    "statW": "WAITING",
    "statX": "OTHER",
    "statDE": "CANCELLED",
    "statD": "FAILED",
    "statEX": "ABNORMAL",
    "statT": "TIMEOUT",
    "statN": "NODE_ERROR",
    "statRQ": "REQUEUED",
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


def normalize_job(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_state = (
        item.get("jobStatus")
        or item.get("jobState")
        or item.get("state")
        or ""
    )
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
            "jobs",
            "logs",
            "submit",
            "cancel",
            "files",
            "mkdir",
            "upload",
            "download",
        }
    )

    def __init__(self, context):
        super().__init__(context)
        self.client = SCNetClient(context)

    def _env(self, name: str, default: str | None = None) -> str | None:
        return self.client.env(name, default)

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
        return self.client.request(
            method,
            url,
            token=token,
            json_body=json_body,
            form=form,
            headers=headers,
        )

    def _regions(self) -> list[dict[str, Any]]:
        return self.client.regions()

    def _select_region(
        self, options: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        requested = (
            options.get("region")
            or self.context.profile.get("OPENAPI_REGION_ID")
            or self._env("SCNET_OPENAPI_REGION_ID")
        )
        return self.client.select_region(str(requested) if requested else None)

    def _center(
        self, options: Mapping[str, Any]
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        requested = (
            options.get("region")
            or self.context.profile.get("OPENAPI_REGION_ID")
            or self._env("SCNET_OPENAPI_REGION_ID")
        )
        return self.client.center(str(requested) if requested else None)

    def _enabled_url(self, center: Mapping[str, Any], field: str) -> str:
        return self.client.enabled_url(center, field)

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

    def discover_all_region_contexts(self) -> list[dict[str, Any]]:
        """Resolve every authorized region without requiring IDs from the user."""
        contexts: list[dict[str, Any]] = []
        center_url = self._env(
            "SCNET_OPENAPI_CENTER_URL",
            "https://www.scnet.cn/ac/openapi/v2/center",
        )
        for region in self._regions():
            region_id = str(region.get("clusterId", ""))
            token = region.get("token")
            if region_id == "0" or not token:
                continue
            center = self._json_request("GET", center_url, token=str(token))
            if not isinstance(center, dict):
                continue
            try:
                hpc_url = self._enabled_url(center, "hpcUrls")
            except BackendError:
                # An account can be authorized for platform/model regions that do not
                # expose an HPC service. They are not job-submission targets.
                continue
            schedulers = self._json_request(
                "GET",
                service_endpoint(hpc_url, "hpc", "/openapi/v2/cluster"),
                token=str(token),
            )
            if not isinstance(schedulers, list):
                schedulers = []
            user_info = center.get("clusterUserInfo") or {}
            contexts.append(
                {
                    "region_id": region_id,
                    "name": region.get("clusterName") or center.get("name"),
                    "username": user_info.get("userName"),
                    "home_path": user_info.get("homePath"),
                    "schedulers": [
                        {
                            "id": str(item.get("id", "")),
                            "name": item.get("text"),
                            "type": item.get("JobManagerType"),
                        }
                        for item in schedulers
                        if isinstance(item, dict)
                    ],
                }
            )
        return contexts

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
        hpc_url, token, scheduler_id, _, _ = self._hpc_context(options)
        realtime_error: str | None = None
        data: Any = None
        try:
            data = self._json_request(
                "GET",
                service_endpoint(hpc_url, "hpc", f"/openapi/v2/jobs/{quote(job_id)}"),
                token=token,
            )
        except BackendError as exc:
            if not self._is_missing_job_error(str(exc)):
                raise
            realtime_error = str(exc)

        if isinstance(data, dict):
            candidate = data
            if candidate.get("jobId") or candidate.get("job_id"):
                result = normalize_job(candidate)
                result["source"] = "realtime"
                if options.get("raw"):
                    result["raw"] = candidate
                return result

        history = self._history_job(
            hpc_url,
            token,
            scheduler_id,
            job_id,
            options,
        )
        if not isinstance(history, dict) or not (
            history.get("jobId") or history.get("job_id")
        ):
            detail = "realtime and history endpoints returned no job record"
            if realtime_error:
                detail += f" ({realtime_error})"
            raise BackendError(detail)
        result = normalize_job(history)
        result["source"] = "history"
        if options.get("raw"):
            result["raw"] = history
        return result

    @staticmethod
    def _is_missing_job_error(text: str) -> bool:
        value = text.lower()
        return any(
            marker in value
            for marker in (
                "unexpected data shape",
                "http 404",
                "not found",
                "does not exist",
                "不存在",
            )
        )

    def _history_job(
        self,
        hpc_url: str,
        token: str,
        scheduler_id: str,
        job_id: str,
        options: Mapping[str, Any],
    ) -> Any:
        if not scheduler_id:
            raise BackendError("history lookup requires a scheduler id")
        path = f"/openapi/v2/historyjobs/{quote(scheduler_id)}/{quote(job_id)}"
        acct_time = str(options.get("acct_time") or "").strip()
        if acct_time:
            path += "?" + urlencode({"acctTime": acct_time})
        return self._json_request(
            "GET",
            service_endpoint(hpc_url, "hpc", path),
            token=token,
        )

    def op_jobs(self, options: Mapping[str, Any]) -> Any:
        hpc_url, token, scheduler_id, _, _ = self._hpc_context(options)
        scope = str(options.get("scope") or "active").strip().lower()
        if scope not in {"active", "history"}:
            raise BackendError("scope must be active or history")
        limit = _bounded_int(options, "limit", 1)
        if limit > 100:
            raise BackendError("limit must be <= 100")
        if scope == "active":
            path = "/openapi/v2/jobs"
            params = {
                "strClusterIDList": scheduler_id,
                "start": 0,
                "limit": limit,
            }
        else:
            days = _bounded_int(options, "days", 1)
            if days > 90:
                raise BackendError("days must be <= 90")
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)
            path = "/openapi/v2/historyjobs"
            params = {
                "strClusterNameList": scheduler_id,
                "timeType": "CUSTOM",
                "isQueryByQueueTime": "false",
                "start": 0,
                "limit": limit,
                "startTime": start.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": end.strftime("%Y-%m-%d %H:%M:%S"),
            }
        data = self._json_request(
            "GET",
            service_endpoint(hpc_url, "hpc", path) + "?" + urlencode(params),
            token=token,
        )
        if isinstance(data, dict):
            items = data.get("items") or data.get("list") or data.get("rows") or []
            total = data.get("total")
        else:
            items = data or []
            total = None
        if not isinstance(items, list):
            raise BackendError("job list endpoint returned an unexpected data shape")
        result = [normalize_job(item) for item in items if isinstance(item, dict)]
        payload = {
            "scope": scope,
            "items": result,
            "total": total if total is not None else len(result),
        }
        return {"data": payload, "raw": data} if options.get("raw") else payload

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
        remote_dir = str(
            options.get("remote_dir")
            or require_option(options, "remote_path")
        )
        if not local_path.is_file():
            raise BackendError(f"local file does not exist: {local_path}")
        if (
            not remote_dir.startswith("/")
            or "\n" in remote_dir
            or "\r" in remote_dir
            or "\x00" in remote_dir
        ):
            raise BackendError("remote upload directory must be absolute")
        chunk_size = int(options.get("chunk_size") or 0)
        if chunk_size < 0:
            raise BackendError("chunk size must be non-negative")
        if chunk_size and chunk_size < 1024 * 1024:
            raise BackendError("chunk size must be at least 1 MiB or 0")
        if chunk_size and local_path.stat().st_size > chunk_size:
            return self._op_chunked_upload(local_path, remote_dir, options, chunk_size)
        efile_url, token, _ = self._efile_context(options)
        content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        self._multipart_request(
            service_endpoint(efile_url, "efile", "/openapi/v2/file/upload"),
            token,
            {
                "cover": "cover" if options.get("cover") else "uncover",
                "path": remote_dir,
            },
            local_path.name,
            local_path.read_bytes(),
            content_type,
        )
        return {
            "local_path": str(local_path),
            "remote_dir": remote_dir,
            "remote_filename": local_path.name,
        }

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
