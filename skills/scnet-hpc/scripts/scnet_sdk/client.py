"""Shared SCNet OpenAPI transport, authentication, and service discovery."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from scnet_backends.base import BackendContext, BackendError
from scnet_credentials import load_openapi_credentials
from scnet_version import VERSION


def canonical_signature(
    access_key: str, timestamp: str, user: str, secret_key: str
) -> str:
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
    split = urlsplit(base_url.rstrip("/"))
    path = split.path.rstrip("/")
    service_part = f"/{service}"
    if not path.endswith(service_part):
        path += service_part
    path += "/" + suffix.lstrip("/")
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


class SCNetClient:
    """One authenticated OpenAPI client shared by service-specific domains."""

    def __init__(self, context: BackendContext):
        self.context = context
        self._regions_cache: list[dict[str, Any]] | None = None
        self._center_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def env(name: str, default: str | None = None) -> str | None:
        value = os.environ.get(name)
        return value if value not in (None, "") else default

    def request(
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
            "User-Agent": f"scnet-hpc/{VERSION}",
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
            raise BackendError(
                f"HTTP {exc.code} from SCNet OpenAPI: {detail[:500]}"
            ) from exc
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
            raise BackendError(
                f"SCNet OpenAPI error {code}: "
                f"{payload.get('msg') or 'unknown error'}"
            )
        return payload.get("data")

    def regions(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if self._regions_cache is not None and not refresh:
            return self._regions_cache
        direct_token = self.env("SCNET_OPENAPI_TOKEN")
        if direct_token:
            region_id = (
                self.env("SCNET_OPENAPI_REGION_ID")
                or self.context.profile.get("OPENAPI_REGION_ID")
                or ""
            )
            self._regions_cache = [
                {
                    "clusterId": region_id,
                    "clusterName": self.env(
                        "SCNET_OPENAPI_REGION_NAME", "configured"
                    ),
                    "token": direct_token,
                }
            ]
            return self._regions_cache

        credentials, _ = load_openapi_credentials()
        user = self.env("SCNET_OPENAPI_USER") or (
            credentials.get("user") if credentials else None
        )
        access_key = self.env("SCNET_OPENAPI_ACCESS_KEY") or (
            credentials.get("access_key") if credentials else None
        )
        secret_key = self.env("SCNET_OPENAPI_SECRET_KEY") or (
            credentials.get("secret_key") if credentials else None
        )
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
                "OpenAPI credentials are not configured; run setup or set "
                + ", ".join(missing)
            )
        timestamp = str(int(time.time()))
        signature = canonical_signature(access_key, timestamp, user, secret_key)
        auth_base = self.env("SCNET_OPENAPI_AUTH_BASE", "https://api.scnet.cn")
        data = self.request(
            "POST",
            auth_base.rstrip("/") + "/api/user/v3/tokens",
            headers={
                "user": user,
                "accessKey": access_key,
                "signature": signature,
                "timestamp": timestamp,
            },
        )
        if not isinstance(data, list):
            raise BackendError("token endpoint returned an unexpected data shape")
        self._regions_cache = [
            item for item in data if isinstance(item, dict)
        ]
        return self._regions_cache

    def select_region(
        self, requested: str | None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        regions = self.regions()
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
            f"{item.get('clusterName')}({item.get('clusterId')})"
            for item in usable
        )
        raise BackendError(
            "multiple OpenAPI regions are available; select one: " + names
        )

    def center(
        self, requested: str | None
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        region, _ = self.select_region(requested)
        region_id = str(region.get("clusterId", ""))
        token = str(region["token"])
        if region_id not in self._center_cache:
            center_url = self.env(
                "SCNET_OPENAPI_CENTER_URL",
                "https://www.scnet.cn/ac/openapi/v2/center",
            )
            data = self.request("GET", center_url, token=token)
            if not isinstance(data, dict):
                raise BackendError(
                    "center endpoint returned an unexpected data shape"
                )
            self._center_cache[region_id] = data
        return self._center_cache[region_id], token, region

    @staticmethod
    def enabled_url(center: Mapping[str, Any], field: str) -> str:
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

    def service_context(
        self, region: str | None, field: str, service: str
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        center, token, selected = self.center(region)
        return (
            self.enabled_url(center, field),
            token,
            selected,
            center,
        )
