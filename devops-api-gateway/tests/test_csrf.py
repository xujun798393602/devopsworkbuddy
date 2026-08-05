from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from gateway.app import GatewaySettings, create_app


@dataclass
class FakeUpstream:
    requests: list[tuple[str, str, object | None, dict[str, str], str]] = field(
        default_factory=list
    )
    refreshes: int = 0
    logged_out: bool = False

    def login(self, username: str) -> dict[str, object]:
        if username != "developer":
            raise PermissionError
        return self.pair("access-1", "refresh-1")

    def refresh(self, refresh_token: str) -> dict[str, object]:
        if refresh_token not in {"refresh-1", "refresh-2"}:
            raise PermissionError
        self.refreshes += 1
        return self.pair("access-2", "refresh-2")

    def logout(self, refresh_token: str) -> None:
        self.logged_out = bool(refresh_token)

    def principal(self, access_token: str) -> dict[str, object]:
        if access_token not in {"access-1", "access-2"}:
            raise PermissionError
        return {
            "id": "user-1",
            "username": "developer",
            "display_name": "Developer",
            "permissions": ["audit.read"],
            "break_glass": False,
        }

    def request(
        self,
        path: str,
        method: str,
        access_token: str,
        payload: object | None,
        headers: Mapping[str, str],
        query_string: str,
    ) -> tuple[int, object]:
        self.requests.append((access_token, method, payload, dict(headers), query_string))
        if access_token == "access-1":
            return 401, {"error": "expired"}
        return 200, {"data": {"path": path, "method": method}}

    @staticmethod
    def pair(access: str, refresh: str) -> dict[str, object]:
        return {"access_token": access, "refresh_token": refresh, "principal": {"id": "user-1"}}


def csrf_headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token, "Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"}


def test_cookie_login_refresh_replay_and_logout() -> None:
    upstream = FakeUpstream()
    client = create_app(upstream, GatewaySettings()).test_client()
    client.get("/bff/session")
    csrf = client.get_cookie("devops_csrf").value
    login = client.post("/bff/auth/login", json={"username": "developer"}, headers=csrf_headers(csrf))
    cookies = login.headers.getlist("Set-Cookie")
    assert any("devops_session=" in item and "HttpOnly" in item and "SameSite=Lax" in item for item in cookies)
    assert any("devops_refresh=" in item and "HttpOnly" in item for item in cookies)
    assert any("devops_csrf=" in item and "HttpOnly" not in item for item in cookies)
    response = client.get("/bff/api/projects")
    assert response.status_code == 200
    assert [call[0] for call in upstream.requests] == ["access-1", "access-2"]
    assert upstream.refreshes == 1
    csrf = client.get_cookie("devops_csrf").value
    logout = client.post("/bff/auth/logout", headers=csrf_headers(csrf))
    assert logout.status_code == 204 and upstream.logged_out
    assert client.get("/bff/api/projects").status_code == 401


def test_proxy_forwards_json_query_and_allowlisted_headers() -> None:
    upstream = FakeUpstream()
    client = create_app(upstream, GatewaySettings()).test_client()
    client.get("/bff/session")
    csrf = client.get_cookie("devops_csrf").value
    client.post(
        "/bff/auth/login",
        json={"username": "developer"},
        headers=csrf_headers(csrf),
    )
    csrf = client.get_cookie("devops_csrf").value
    response = client.post(
        "/bff/api/v1/projects/project-1/requirements?include=links",
        json={"title": "Requirement"},
        headers={
            **csrf_headers(csrf),
            "Idempotency-Key": "request-1",
            "X-Actor-Id": "attacker-controlled",
            "X-Platform-Permissions": "workflow.template.manage",
            "X-Ignored-Header": "not-forwarded",
        },
    )
    assert response.status_code == 200
    _, method, payload, headers, query = upstream.requests[-1]
    assert method == "POST"
    assert payload == {"title": "Requirement"}
    assert headers["Idempotency-Key"] == "request-1"
    assert headers["X-Actor-Id"] == "user-1"
    assert headers["X-Platform-Permissions"] == "audit.read"
    assert "X-Ignored-Header" not in headers
    assert query == "include=links"


def test_write_requires_matching_csrf_and_origin() -> None:
    client = create_app(FakeUpstream(), GatewaySettings()).test_client()
    assert client.post("/bff/auth/logout").status_code == 403
    client.set_cookie("devops_csrf", "same")
    assert client.post("/bff/auth/logout", headers=csrf_headers("different")).status_code == 403


def test_production_requires_secure_cookies() -> None:
    with pytest.raises(RuntimeError):
        GatewaySettings(environment="production", secure_cookies=False).validate()
