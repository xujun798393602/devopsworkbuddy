"""HTTP adapter connecting the browser BFF to IAM and domain APIs."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HttpUpstream:
    """Small standard-library upstream client with bounded timeouts."""

    iam_url: str
    routes: dict[str, str]
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> HttpUpstream:
        iam_url = os.getenv("IAM_URL", "").rstrip("/")
        if not iam_url:
            raise RuntimeError("IAM_URL is required")
        routes = {
            "projects": os.getenv("PROJECT_URL", ""),
            "requirements": os.getenv("REQUIREMENT_URL", ""),
            "test-folders": os.getenv("TP_URL", ""),
            "test-design-sessions": os.getenv("TP_URL", ""),
            "test-environments": os.getenv("TP_URL", ""),
            "test-plans": os.getenv("TP_URL", ""),
            "test-executions": os.getenv("TP_URL", ""),
            "automation-result-ingestions": os.getenv("TP_URL", ""),
            "traceability": os.getenv("TP_URL", ""),
            "defects": os.getenv("TD_URL", ""),
            "workflow-templates": os.getenv("WORKFLOW_URL", ""),
            "workflow-instances": os.getenv("WORKFLOW_URL", ""),
            "audit-records": os.getenv("AUDIT_URL", ""),
            "me": os.getenv("NOTIFICATION_URL", ""),
        }
        if any(not value for value in routes.values()):
            raise RuntimeError("All domain upstream URLs are required")
        return cls(iam_url=iam_url, routes=routes)

    def login(self, username: str) -> dict[str, object]:
        status, body = self._request(f"{self.iam_url}/api/v1/auth/login", "POST", {"username": username})
        if status != 201:
            raise PermissionError("Authentication failed")
        return self._normalize_pair(body)

    def refresh(self, refresh_token: str) -> dict[str, object]:
        status, body = self._request(
            f"{self.iam_url}/api/v1/auth/refresh", "POST", {"refresh_token": refresh_token}
        )
        if status != 200:
            raise PermissionError("Refresh failed")
        return self._normalize_pair(body)

    def logout(self, refresh_token: str) -> None:
        self._request(f"{self.iam_url}/api/v1/auth/logout", "POST", {"refresh_token": refresh_token})

    def principal(self, access_token: str) -> dict[str, object]:
        """Resolve browser identity through IAM instead of trusting client headers."""
        status, body = self._request(
            f"{self.iam_url}/api/v1/me",
            "GET",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise PermissionError("Access token is invalid")
        return dict(body["data"])

    def request(
        self,
        path: str,
        method: str,
        access_token: str,
        payload: object | None,
        headers: Mapping[str, str],
        query_string: str,
    ) -> tuple[int, object]:
        route_key = self._route_key(path)
        base_url = self.routes.get(route_key)
        if base_url is None:
            return 404, {"error_code": "UPSTREAM_ROUTE_NOT_FOUND"}
        target = f"{base_url.rstrip('/')}/api/{path.lstrip('/')}"
        if query_string:
            target = f"{target}?{query_string}"
        return self._request(
            target,
            method,
            payload,
            {**headers, "Authorization": f"Bearer {access_token}"},
        )

    @staticmethod
    def _route_key(path: str) -> str:
        """Resolve a versioned domain path without trusting a client-provided host."""
        segments = [segment for segment in path.strip("/").split("/") if segment]
        if segments[:1] == ["v1"]:
            segments = segments[1:]
        if not segments:
            return ""
        if segments[0] == "projects" and len(segments) >= 3:
            return segments[2]
        return segments[0]

    def _request(
        self,
        url: str,
        method: str,
        payload: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, object]:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            raw = error.read()
            return error.code, json.loads(raw) if raw else {}

    @staticmethod
    def _normalize_pair(body: object) -> dict[str, object]:
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise PermissionError("Invalid IAM response")
        data = dict(body["data"])
        data["principal"] = data.get("principal", {"id": data.get("user_id", "dev-user")})
        return data
