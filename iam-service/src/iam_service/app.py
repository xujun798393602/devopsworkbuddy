"""IAM Flask application factory."""
from uuid import uuid4

from flask import Flask, g, jsonify, request
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from iam_service.auth.break_glass import BreakGlassService, TotpVerifier
from iam_service.auth.providers import LocalDevProvider
from iam_service.auth.repository import (
    IamRepository,
    InMemoryIamRepository,
    SqlAlchemyIamRepository,
)
from iam_service.auth.service import SessionService
from iam_service.auth.tokens import TokenService
from iam_service.config import Settings


def create_app(
    settings: Settings | None = None,
    totp_verifier: TotpVerifier | None = None,
    repository: IamRepository | None = None,
) -> Flask:
    """Create IAM with injectable storage and persistent container defaults."""
    app = Flask(__name__)
    cfg = settings or Settings.from_env()
    repo = repository or _repository(cfg)
    service = SessionService(
        repo,
        TokenService(cfg),
        LocalDevProvider(cfg.local_dev_auth_enabled),
        cfg.refresh_ttl,
    )
    app.extensions["session_service"] = service
    break_glass = (
        BreakGlassService(service, totp_verifier, cfg.break_glass_allowed_cidrs)
        if totp_verifier
        else None
    )

    @app.before_request
    def trace() -> None:
        g.trace_id = request.headers.get("X-Trace-Id", str(uuid4()))

    @app.after_request
    def headers(response):
        response.headers["X-Trace-Id"] = g.trace_id
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": cfg.service_name})

    @app.get("/ready")
    def ready():
        try:
            service.repo.check()
        except (OSError, RuntimeError, SQLAlchemyError):
            return jsonify(
                {"status": "error", "checks": {"database": {"status": "error"}}}
            ), 503
        return jsonify(
            {
                "status": "ok",
                "checks": {
                    "configuration": {"status": "ok"},
                    "database": {"status": "ok"},
                },
            }
        )

    @app.post("/api/v1/auth/login")
    def login():
        body = request.get_json(silent=True) or {}
        try:
            result = service.login(str(body.get("username", "")))
        except PermissionError:
            return problem(401, "AUTHENTICATION_FAILED", "Authentication failed")
        return success(result), 201

    @app.post("/api/v1/emergency-auth/login")
    def emergency_login():
        if break_glass is None or not cfg.break_glass_enabled:
            return problem(
                404, "NOT_FOUND", "Emergency authentication is unavailable"
            )
        body = request.get_json(silent=True) or {}
        try:
            result = break_glass.login(
                str(body.get("username", "")),
                str(body.get("code", "")),
                str(body.get("reason", "")),
                str(body.get("ticket", "")),
                request.remote_addr or "",
            )
        except (PermissionError, ValueError):
            return problem(
                401, "BREAK_GLASS_DENIED", "Emergency authentication denied"
            )
        return success(result), 201

    @app.post("/api/v1/auth/refresh")
    def refresh():
        body = request.get_json(silent=True) or {}
        try:
            result = service.refresh(str(body.get("refresh_token", "")))
        except PermissionError as error:
            return problem(401, "REFRESH_REJECTED", str(error))
        return success(result)

    @app.post("/api/v1/auth/logout")
    def logout():
        body = request.get_json(silent=True) or {}
        service.logout(str(body.get("refresh_token", "")))
        return "", 204

    @app.get("/api/v1/me")
    def me():
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        try:
            claims = service.tokens.verify_access(token)
        except (KeyError, TypeError, ValueError):
            return problem(
                401, "INVALID_ACCESS_TOKEN", "Access token is invalid"
            )
        user = service.repo.get_user(str(claims["sub"]))
        if user is None:
            return problem(
                401, "INVALID_ACCESS_TOKEN", "Access token is invalid"
            )
        return success(
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "permissions": list(user.permissions),
                "break_glass": bool(claims["break_glass"]),
            }
        )

    @app.get("/.well-known/jwks.json")
    def jwks():
        return jsonify(
            {"keys": [], "warning": "HS256 development key is never published"}
        )

    return app


def _repository(settings: Settings) -> IamRepository:
    """Select persistent storage when configured, otherwise controlled local memory."""
    if settings.database_url:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        return SqlAlchemyIamRepository(engine)
    if settings.app_env in {"production", "container"}:
        raise RuntimeError("DATABASE_URL is required in production")
    return InMemoryIamRepository()


def success(data: object):
    return jsonify({"data": data, "meta": {"trace_id": g.trace_id}})


def problem(status: int, code: str, detail: str):
    return (
        jsonify(
            {
                "type": "about:blank",
                "title": code,
                "status": status,
                "detail": detail,
                "error_code": code,
                "trace_id": g.trace_id,
            }
        ),
        status,
        {"Content-Type": "application/problem+json"},
    )
