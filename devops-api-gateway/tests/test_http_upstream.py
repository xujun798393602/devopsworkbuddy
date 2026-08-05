"""Tests for the bounded HTTP domain adapter."""

import io
import json
import urllib.error
from typing import Self
from unittest.mock import patch

from gateway.http_upstream import HttpUpstream


class FakeResponse:
    """Minimal context-managed urllib response."""

    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self._body = json.dumps(body).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def adapter() -> HttpUpstream:
    """Create an adapter with deterministic service URLs."""
    return HttpUpstream(
        iam_url="http://iam:18140",
        routes={
            "projects": "http://project:18100",
            "requirements": "http://requirement:18110",
            "test-plans": "http://tp:18120",
            "defects": "http://td:18130",
            "workflow-instances": "http://workflow:18150",
            "audit-records": "http://audit:18160",
            "me": "http://notification:18170",
        },
    )


def test_domain_request_routes_versioned_project_resource() -> None:
    captured = {}

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(201, {"data": {"id": "requirement-1"}})

    with patch("urllib.request.urlopen", side_effect=open_request):
        status, body = adapter().request(
            "v1/projects/project-1/requirements",
            "POST",
            "access-token",
            {"title": "Requirement"},
            {"Idempotency-Key": "request-1", "Content-Type": "application/json"},
            "expand=links",
        )

    request = captured["request"]
    assert status == 201
    assert body == {"data": {"id": "requirement-1"}}
    assert request.full_url == (
        "http://requirement:18110/api/v1/projects/project-1/requirements?expand=links"
    )
    assert request.get_header("Authorization") == "Bearer access-token"
    assert request.get_header("Idempotency-key") == "request-1"
    assert json.loads(request.data) == {"title": "Requirement"}
    assert captured["timeout"] == 5.0


def test_unknown_domain_route_is_rejected_without_network() -> None:
    with patch("urllib.request.urlopen") as open_request:
        status, body = adapter().request(
            "v1/unknown",
            "GET",
            "access-token",
            None,
            {},
            "",
        )
    assert status == 404
    assert body == {"error_code": "UPSTREAM_ROUTE_NOT_FOUND"}
    open_request.assert_not_called()


def test_http_problem_body_is_preserved() -> None:
    error = urllib.error.HTTPError(
        "http://project:18100/api/v1/projects",
        403,
        "Forbidden",
        {},
        io.BytesIO(b'{"error_code":"PERMISSION_DENIED"}'),
    )
    with patch("urllib.request.urlopen", side_effect=error):
        status, body = adapter().request(
            "v1/projects",
            "GET",
            "access-token",
            None,
            {},
            "",
        )
    assert status == 403
    assert body == {"error_code": "PERMISSION_DENIED"}
