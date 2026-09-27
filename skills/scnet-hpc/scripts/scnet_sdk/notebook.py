"""Read-only Notebook domain built on the shared SCNet OpenAPI client."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from scnet_backends.base import BackendError

from .client import SCNetClient, service_endpoint


SENSITIVE_FIELDS = {
    "sshPassword",
    "password",
    "token",
    "userToken",
}


def _safe_url(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    split = urlsplit(str(value))
    return {
        "origin": urlunsplit((split.scheme, split.netloc, "", "", "")),
        "path": split.path,
        "credentials_redacted": bool(split.query),
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in SENSITIVE_FIELDS:
                result[key] = "<redacted>" if item else item
            elif key in {"url", "sshUrl", "serviceUrl"}:
                result[key] = _safe_url(item)
            else:
                result[key] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class NotebookService:
    def __init__(self, client: SCNetClient):
        self.client = client

    def _context(
        self, region: str | None
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        return self.client.service_context(region, "aiUrls", "ai")

    def regions(self) -> list[dict[str, Any]]:
        result = []
        for region in self.client.regions():
            region_id = str(region.get("clusterId", ""))
            if region_id == "0" or not region.get("token"):
                continue
            try:
                ai_url, _, _, center = self._context(region_id)
            except BackendError:
                continue
            result.append(
                {
                    "region_id": region_id,
                    "name": region.get("clusterName") or center.get("name"),
                    "available": True,
                    "service": "notebook",
                    "endpoint_origin": _safe_url(ai_url),
                }
            )
        return result

    def resources(
        self, region: str, resource_id: str = ""
    ) -> list[dict[str, Any]]:
        _, token, selected, _ = self._context(region)
        params: dict[str, Any] = {
            "clusterIds": str(selected.get("clusterId"))
        }
        if resource_id:
            params["resourceId"] = resource_id
        data = self.client.request(
            "GET",
            "https://www.scnet.cn/ac/openapi/v2/resources/accelerators?"
            + urlencode(params),
            token=token,
        )
        return _redact(data if isinstance(data, list) else [])

    def images(
        self,
        region: str,
        *,
        access: str = "public",
        image_type: str = "",
        accelerator_type: str = "",
        name: str = "",
        start: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        ai_url, token, _, _ = self._context(region)
        body = {
            "access": access,
            "start": start,
            "limit": limit,
            "sort": "DESC",
            "orderBy": "create_time",
            "name": name,
            "type": image_type,
            "acceleratorType": accelerator_type,
        }
        data = self.client.request(
            "POST",
            service_endpoint(
                ai_url, "ai", "/openapi/v2/image/images"
            ),
            token=token,
            json_body=body,
        )
        return _redact(data if isinstance(data, dict) else {"data": data})

    def list_instances(
        self,
        region: str,
        *,
        name: str = "",
        status: str = "",
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        ai_url, token, _, _ = self._context(region)
        params: dict[str, Any] = {"page": page, "size": size}
        if name:
            params["notebookName"] = name
        if status:
            params["notebookStatus"] = status
        data = self.client.request(
            "GET",
            service_endpoint(
                ai_url, "ai", "/openapi/v2/notebook/list"
            )
            + "?"
            + urlencode(params),
            token=token,
        )
        return _redact(data if isinstance(data, dict) else {"records": []})

    def detail(self, region: str, notebook_id: str) -> dict[str, Any]:
        ai_url, token, _, _ = self._context(region)
        data = self.client.request(
            "GET",
            service_endpoint(
                ai_url, "ai", "/openapi/v2/notebook/detail"
            )
            + "?"
            + urlencode({"notebookId": notebook_id}),
            token=token,
        )
        return _redact(data if isinstance(data, dict) else {})

    def url(
        self, region: str, notebook_id: str, *, reveal: bool = False
    ) -> dict[str, Any]:
        ai_url, token, _, _ = self._context(region)
        data = self.client.request(
            "GET",
            service_endpoint(
                ai_url, "ai", "/openapi/v2/notebook/url"
            )
            + "?"
            + urlencode({"notebookId": notebook_id}),
            token=token,
        )
        if not isinstance(data, dict):
            return {}
        return data if reveal else _redact(data)

    @staticmethod
    def _number(value: Any, default: int = 10**15) -> int:
        try:
            return int(re.sub(r"[^0-9]", "", str(value)))
        except (TypeError, ValueError):
            return default

    def create_plan(
        self,
        region: str,
        *,
        resource_group: str = "",
        image_id: str = "",
        accelerator_number: int = 1,
        mount_home: bool = True,
        start_command: str = "",
    ) -> dict[str, Any]:
        if accelerator_number < 1:
            raise BackendError("accelerator number must be at least 1")
        resources = self.resources(region)
        candidates = [
            item
            for item in resources
            if int(item.get("maxFreeNum") or 0) >= accelerator_number
        ]
        if resource_group:
            candidates = [
                item
                for item in candidates
                if item.get("resourceGroupCode") == resource_group
            ]
        candidates.sort(
            key=lambda item: (
                self._number(item.get("ramSize")),
                self._number(item.get("cpuNumber")),
                self._number(item.get("imageSize")),
            )
        )
        if not candidates:
            raise BackendError("no available Notebook resource matches the request")
        resource = candidates[0]
        accelerator_type = str(resource.get("resourceType") or "").lower()
        image_data = self.images(
            region,
            access="public",
            accelerator_type=accelerator_type,
            limit=300,
        )
        images = image_data.get("data") or image_data.get("records") or []
        trusted = [
            item
            for item in images
            if item.get("status") == "Completed"
            and (
                item.get("isPresetImage") is True
                or str(item.get("user", "")).lower() in {"admin", "system"}
            )
            and "jupyter" in (
                str(item.get("name", ""))
                + " "
                + str(item.get("tag", ""))
                + " "
                + str(item.get("version", ""))
            ).lower()
        ]
        if image_id:
            trusted = [
                item for item in trusted if str(item.get("id")) == image_id
            ]
        trusted.sort(key=lambda item: self._number(item.get("imageSize")))
        if not trusted:
            raise BackendError("no trusted preset Jupyter image matches the request")
        image = trusted[0]
        image_name = (
            image.get("version")
            or (
                f"{image.get('name')}:{image.get('tag')}"
                if image.get("tag")
                else image.get("name")
            )
        )
        return {
            "region_id": region,
            "resource": resource,
            "image": image,
            "request": {
                "clusterId": region,
                "imagePath": image.get("path"),
                "imageName": image_name,
                "imageSize": str(image.get("imageSize") or ""),
                "acceleratorType": str(
                    resource.get("resourceType") or ""
                ).upper(),
                "acceleratorNumber": str(accelerator_number),
                "resourceGroupCode": resource.get("resourceGroupCode"),
                "mountHome": mount_home,
                "mountInfo": [],
                **(
                    {"startCommand": start_command}
                    if start_command
                    else {}
                ),
            },
            "summary": {
                "region": resource.get("clusterName") or region,
                "resource": resource.get("resourceName"),
                "cards": accelerator_number,
                "cpu": resource.get("cpuNumber"),
                "ram": resource.get("ramSize"),
                "free_cards": resource.get("maxFreeNum"),
                "image": image_name,
                "image_size": image.get("imageSize"),
                "mount_home": mount_home,
            },
        }

    def create(self, region: str, plan: dict[str, Any]) -> dict[str, Any]:
        _, token, _, _ = self._context(region)
        data = self.client.request(
            "POST",
            "https://www.scnet.cn/ac/openapi/v2/notebook/actions/create",
            token=token,
            json_body=plan["request"],
        )
        return _redact(data if isinstance(data, dict) else {})

    def start(self, region: str, notebook_id: str) -> Any:
        _, token, _, _ = self._context(region)
        return self.client.request(
            "POST",
            "https://www.scnet.cn/ac/openapi/v2/notebook/actions/start",
            token=token,
            json_body={"notebookId": notebook_id},
        )

    def stop(
        self, region: str, notebook_id: str, *, save_environment: bool = False
    ) -> Any:
        ai_url, token, _, _ = self._context(region)
        return self.client.request(
            "POST",
            service_endpoint(
                ai_url, "ai", "/openapi/v2/notebook/actions/stop"
            ),
            token=token,
            json_body={
                "notebookId": notebook_id,
                "saveEnv": save_environment,
            },
        )

    def release(self, region: str, notebook_id: str) -> Any:
        ai_url, token, _, _ = self._context(region)
        return self.client.request(
            "POST",
            service_endpoint(
                ai_url, "ai", "/openapi/v2/notebook/actions/release"
            ),
            token=token,
            json_body={"id": notebook_id},
        )

    def rename(self, region: str, notebook_id: str, name: str) -> Any:
        if not name.strip():
            raise BackendError("Notebook name must not be empty")
        ai_url, token, _, _ = self._context(region)
        return self.client.request(
            "POST",
            service_endpoint(
                ai_url, "ai", "/openapi/v2/notebook/name"
            ),
            token=token,
            json_body={"id": notebook_id, "notebookName": name.strip()},
        )

    def wait_status(
        self,
        region: str,
        notebook_id: str,
        statuses: set[str],
        *,
        timeout: int = 600,
        interval: int = 5,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.detail(region, notebook_id)
            if last.get("notebookStatus") in statuses:
                return last
            time.sleep(interval)
        raise BackendError(
            f"Notebook {notebook_id} did not reach {sorted(statuses)}; "
            f"last={last.get('notebookStatus')}"
        )
