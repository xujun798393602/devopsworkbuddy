"""Flask API for the requirement service."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from flask import Flask, Response, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.local import LocalProxy

from requirement_service.config import Config
from requirement_service.database import build_engine
from requirement_service.domain import DomainError, Requirement
from requirement_service.repository import (
    AllowAllAuthorizer,
    MemoryUnitOfWork,
    SqlAlchemyRuntime,
)
from requirement_service.service import RequirementService, UnitOfWork


def problem(status: int, code: str, detail: str) -> Response:
    """Return an RFC 9457 problem response."""
    response = jsonify(
        type=f"urn:problem:{code.lower()}",
        title=code.replace("_", " ").title(),
        status=status,
        detail=detail,
        code=code,
    )
    response.status_code = status
    response.content_type = "application/problem+json"
    return response


def create_app(
    uow: UnitOfWork | None = None,
    config: Config | None = None,
) -> Flask:
    """Create an independently testable, production-safe Flask application."""
    app = Flask(__name__)
    settings = config or Config.from_env()
    runtime: SqlAlchemyRuntime | None = None
    memory_store = uow
    if memory_store is None and settings.database_url:
        runtime = SqlAlchemyRuntime(build_engine(settings.database_url))
    elif memory_store is None:
        memory_store = MemoryUnitOfWork()

    def current_store() -> UnitOfWork:
        if memory_store is not None:
            return memory_store
        if "requirement_uow" not in g:
            if runtime is None:
                raise RuntimeError("Requirement SQL runtime is not configured")
            g.requirement_uow = runtime.unit_of_work()
        return g.requirement_uow

    def current_service() -> RequirementService:
        if "requirement_service" not in g:
            g.requirement_service = RequirementService(
                current_store(), AllowAllAuthorizer()
            )
        return g.requirement_service

    store = LocalProxy(current_store)
    service = LocalProxy(current_service)
    app.extensions.update(requirement_uow=memory_store, requirement_runtime=runtime)

    @app.teardown_request
    def close_session(error: BaseException | None) -> None:
        request_store = g.pop("requirement_uow", None)
        g.pop("requirement_service", None)
        if error is not None and request_store is not None:
            request_store.rollback()
        if runtime is not None:
            runtime.remove()

    @app.errorhandler(DomainError)
    def handle_domain_error(error: DomainError) -> Response:
        store.rollback()
        return problem(error.status, error.code, error.detail)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": "requirement-service"}

    @app.get("/ready")
    def ready() -> tuple[dict[str, Any], int] | dict[str, Any]:
        if runtime is None:
            return {
                "status": "ready",
                "dependencies": {"database": "memory-test-adapter"},
            }
        try:
            runtime.ready()
        except SQLAlchemyError:
            return {
                "status": "not-ready",
                "dependencies": {"database": "unavailable"},
            }, 503
        return {"status": "ready", "dependencies": {"database": "ok"}}

    @app.post("/api/v1/projects/<uuid:project_id>/requirements")
    def create_requirement(project_id: UUID) -> Response | tuple[Response, int]:
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return problem(
                400,
                "IDEMPOTENCY_KEY_REQUIRED",
                "Idempotency-Key header is required",
            )
        actor = request.headers.get("X-Actor-Id", "")
        try:
            actor_id = UUID(actor)
        except ValueError:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        payload = request.get_json(silent=True) or {}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        prior = store.get_idempotency(str(project_id), str(actor_id), key)
        if prior:
            if prior[0] != digest:
                return problem(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Key was already used with a different payload",
                )
            return jsonify(prior[1]), prior[2]
        try:
            value = service.create(actor_id, project_id, payload)
            body = requirement_body(value)
            store.save_idempotency(
                str(project_id), str(actor_id), key, digest, body, 201
            )
            store.commit()
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        response = jsonify(body)
        response.status_code = 201
        response.headers["ETag"] = '"1"'
        return response

    @app.get("/api/v1/projects/<uuid:project_id>/requirements/<uuid:requirement_id>")
    def get_requirement(project_id: UUID, requirement_id: UUID) -> Response:
        value = service.get(project_id, requirement_id)
        if value is None:
            return problem(404, "RESOURCE_NOT_FOUND", "Requirement is not visible")
        response = jsonify(
            data={
                "id": str(value.id),
                "project_id": str(value.project_id),
                "title": value.title,
                "status": value.status.value,
                "version": value.version,
            },
            meta={"trace_id": request.headers.get("X-Trace-Id", "local")},
        )
        response.headers["ETag"] = f'"{value.version}"'
        return response

    return app


def requirement_body(value: Requirement) -> dict[str, Any]:
    """Serialize a created requirement response."""
    return {
        "data": {
            "id": str(value.id),
            "project_id": str(value.project_id),
            "business_no": value.business_no,
            "title": value.title,
            "type": value.type.value,
            "status": value.status.value,
            "version": value.version,
        },
        "meta": {"trace_id": request.headers.get("X-Trace-Id", "local")},
    }


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=18110)
