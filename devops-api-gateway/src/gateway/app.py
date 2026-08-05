"""Same-site browser BFF with cookie-only upstream authentication."""

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from flask import Flask, Response, jsonify, request

from gateway.csrf import validate_csrf
from gateway.singleflight import RefreshSingleFlight


class IamUpstream(Protocol):
    """IAM operations consumed by the BFF."""

    def login(self, username: str) -> dict[str, object]: ...
    def refresh(self, refresh_token: str) -> dict[str, object]: ...
    def logout(self, refresh_token: str) -> None: ...
    def principal(self, access_token: str) -> dict[str, object]: ...
    def request(
        self,
        path: str,
        method: str,
        access_token: str,
        payload: object | None,
        headers: Mapping[str, str],
        query_string: str,
    ) -> tuple[int, object]: ...


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    """Security-sensitive gateway configuration."""

    environment: str = "development"
    secure_cookies: bool = False
    trusted_origins: tuple[str, ...] = ("http://localhost:5173",)

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        environment = os.getenv("APP_ENV", "development")
        secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
        origins = tuple(
            origin.strip()
            for origin in os.getenv("TRUSTED_ORIGINS", "http://localhost:5173").split(",")
            if origin.strip()
        )
        value = cls(
            environment=environment,
            secure_cookies=secure,
            trusted_origins=origins,
        )
        value.validate()
        return value

    def validate(self) -> None:
        if self.environment in {"production", "container"} and not self.secure_cookies:
            raise RuntimeError("Secure cookies are required outside development")
        if not self.trusted_origins:
            raise RuntimeError("At least one trusted origin is required")


def create_app(
    upstream: IamUpstream,
    settings: GatewaySettings | None = None,
) -> Flask:
    """Create a BFF using an injected IAM/upstream adapter."""
    app = Flask(__name__)
    config = settings or GatewaySettings.from_env()
    origins = set(config.trusted_origins)
    refresh_flights = RefreshSingleFlight()

    @app.before_request
    def csrf_guard() -> Response | tuple[Response, int, dict[str, str]] | None:
        if request.path.startswith("/bff/") and not validate_csrf(request, origins):
            return problem(403, "CSRF_REJECTED", "CSRF validation failed")
        return None

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok", "service": "devops-api-gateway"})

    @app.get("/bff/session")
    def session() -> Response:
        access_token = request.cookies.get("devops_session", "")
        principal: dict[str, object] | None = None
        if access_token:
            try:
                principal = upstream.principal(access_token)
            except PermissionError:
                principal = None
        response = jsonify(
            {"data": {"authenticated": principal is not None, "principal": principal}}
        )
        if not request.cookies.get("devops_csrf"):
            response.set_cookie("devops_csrf", secrets.token_urlsafe(32), **csrf_cookie(config))
        if access_token and principal is None:
            clear_auth_cookies(response, config)
        return response

    @app.post("/bff/auth/login")
    def login() -> Response | tuple[Response, int, dict[str, str]]:
        body = request.get_json(silent=True) or {}
        try:
            pair = upstream.login(str(body.get("username", "")))
        except PermissionError:
            return problem(401, "AUTHENTICATION_FAILED", "Authentication failed")
        response = jsonify({"data": {"principal": pair["principal"]}})
        set_auth_cookies(response, pair, config)
        return response

    @app.post("/bff/auth/refresh")
    def refresh() -> Response | tuple[Response, int, dict[str, str]]:
        pair = refresh_pair(upstream, request.cookies.get("devops_refresh", ""))
        if pair is None:
            response, status, headers = problem(401, "SESSION_EXPIRED", "Session expired")
            clear_auth_cookies(response, config)
            return response, status, headers
        response = jsonify({"data": {"principal": pair["principal"]}})
        set_auth_cookies(response, pair, config)
        return response

    @app.post("/bff/auth/logout")
    def logout() -> Response:
        refresh_token = request.cookies.get("devops_refresh", "")
        if refresh_token:
            upstream.logout(refresh_token)
        response = Response(status=204)
        clear_auth_cookies(response, config)
        return response

    @app.route("/bff/api/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def proxy(path: str) -> Response | tuple[Response, int, dict[str, str]]:
        access_token = request.cookies.get("devops_session", "")
        if not access_token:
            return problem(401, "SESSION_REQUIRED", "Authentication is required")
        payload = request.get_json(silent=True) if request.is_json else None
        try:
            principal = upstream.principal(access_token)
        except PermissionError:
            return problem(401, "SESSION_EXPIRED", "Session expired")
        forwarded_headers = proxy_headers(request.headers, principal)
        query_string = request.query_string.decode("ascii", errors="strict")
        status, body = upstream.request(
            path,
            request.method,
            access_token,
            payload,
            forwarded_headers,
            query_string,
        )
        if status == 401:
            refresh_token = request.cookies.get("devops_refresh", "")
            pair = refresh_flights.run(refresh_token, lambda: refresh_pair(upstream, refresh_token))
            if pair is None:
                return problem(401, "SESSION_EXPIRED", "Session expired")
            status, body = upstream.request(
                path,
                request.method,
                str(pair["access_token"]),
                payload,
                forwarded_headers,
                query_string,
            )
            response = jsonify(body)
            response.status_code = status
            set_auth_cookies(response, pair, config)
            return response
        response = jsonify(body)
        response.status_code = status
        return response

    return app


def proxy_headers(
    headers: Mapping[str, str],
    principal: Mapping[str, object],
) -> dict[str, str]:
    """Forward safe request metadata and inject identity from verified IAM state."""
    allowed = {"content-type", "idempotency-key", "if-match", "x-trace-id"}
    forwarded = {
        name: value for name, value in headers.items() if name.lower() in allowed
    }
    actor_id = str(principal.get("id", "")).strip()
    if not actor_id:
        raise PermissionError("Verified principal has no actor id")
    permissions = principal.get("permissions", ())
    if not isinstance(permissions, (list, tuple)):
        raise PermissionError("Verified principal permissions are invalid")
    forwarded["X-Actor-Id"] = actor_id
    forwarded["X-Platform-Permissions"] = " ".join(
        str(permission) for permission in permissions
    )
    return forwarded


def refresh_pair(upstream: IamUpstream, refresh_token: str) -> dict[str, object] | None:
    if not refresh_token:
        return None
    try:
        return upstream.refresh(refresh_token)
    except PermissionError:
        return None


def set_auth_cookies(response: Response, pair: dict[str, object], settings: GatewaySettings) -> None:
    common = {"secure": settings.secure_cookies, "httponly": True, "samesite": "Lax", "path": "/"}
    response.set_cookie("devops_session", str(pair["access_token"]), **common)
    response.set_cookie("devops_refresh", str(pair["refresh_token"]), **common)
    response.set_cookie("devops_csrf", secrets.token_urlsafe(32), **csrf_cookie(settings))


def clear_auth_cookies(response: Response, settings: GatewaySettings) -> None:
    for name, httponly in (("devops_session", True), ("devops_refresh", True), ("devops_csrf", False)):
        response.delete_cookie(name, path="/", secure=settings.secure_cookies, httponly=httponly, samesite="Lax")


def csrf_cookie(settings: GatewaySettings) -> dict[str, object]:
    return {"secure": settings.secure_cookies, "httponly": False, "samesite": "Lax", "path": "/"}


def problem(status: int, code: str, detail: str) -> tuple[Response, int, dict[str, str]]:
    return jsonify({"type": "about:blank", "title": code, "status": status, "detail": detail, "error_code": code}), status, {"Content-Type": "application/problem+json"}
