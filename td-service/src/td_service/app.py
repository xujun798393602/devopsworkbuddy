"""Flask HTTP adapter for the defect service."""
from __future__ import annotations

import hashlib
import json
from typing import Any, cast
from uuid import UUID

from flask import Flask, Response, g, jsonify, request
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from td_service.config import Config
from td_service.domain import DomainError, FixEvidence, VerificationEvidence
from td_service.repository import (
    AllowAllAuthorizer,
    MemoryUnitOfWork,
    SqlAlchemyRuntime,
)
from td_service.service import DefectService, UnitOfWork


def _problem(status: int, code: str, detail: str) -> tuple[Response, int]:
    response = jsonify(
        type=f"urn:problem:{code.lower()}",
        title=code.replace("_", " ").title(),
        status=status,
        detail=detail,
        code=code,
    )
    response.content_type = "application/problem+json"
    return response, status


def _actor_id() -> UUID:
    try:
        return UUID(request.headers.get("X-Actor-Id", ""))
    except ValueError as error:
        raise DomainError("UNAUTHENTICATED", "A valid actor identity is required", 401) from error


def _serialize(defect: Any) -> dict[str, Any]:
    sla = defect.sla
    return {
        "id": str(defect.id),
        "project_id": str(defect.project_id),
        "business_no": defect.business_no,
        "title": defect.title,
        "description": defect.description,
        "severity": defect.severity,
        "priority": defect.priority,
        "defect_type": defect.defect_type,
        "status": defect.status.value,
        "reporter_id": str(defect.reporter_id),
        "assignee_id": str(defect.assignee_id) if defect.assignee_id else None,
        "verifier_id": str(defect.verifier_id) if defect.verifier_id else None,
        "reopen_count": defect.reopen_count,
        "version": defect.version,
        "sla": {
            "policy_key": sla.policy_key,
            "policy_version": sla.policy_version,
            "response_due_at": sla.response_due_at.isoformat(),
            "resolution_due_at": sla.resolution_due_at.isoformat(),
            "response_breached": sla.response_breached,
            "resolution_breached": sla.resolution_breached,
        }
        if sla
        else None,
    }


def _request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def create_app(
    uow: UnitOfWork | None = None,
    config: Config | None = None,
) -> Flask:
    """Create TD with explicit test adapters or production SQLAlchemy wiring."""
    app = Flask(__name__)
    settings = config or Config.from_env()
    runtime: SqlAlchemyRuntime | None = None
    memory_store: UnitOfWork | None = uow
    if memory_store is None and settings.database_url:
        runtime = SqlAlchemyRuntime(
            create_engine(settings.database_url, pool_pre_ping=True)
        )
    elif memory_store is None:
        memory_store = MemoryUnitOfWork()

    def get_uow() -> UnitOfWork:
        if memory_store is not None:
            return memory_store
        if "td_uow" not in g:
            assert runtime is not None
            g.td_uow = runtime.unit_of_work()
        return cast(UnitOfWork, g.td_uow)

    def get_service() -> DefectService:
        return DefectService(get_uow(), AllowAllAuthorizer())

    @app.teardown_appcontext
    def close_session(error: BaseException | None) -> None:
        if runtime is None:
            return
        current = g.pop("td_uow", None)
        if error is not None and current is not None:
            current.rollback()
        runtime.remove()

    @app.errorhandler(DomainError)
    def handle_domain_error(error: DomainError) -> tuple[Response, int]:
        return _problem(error.status, error.code, error.detail)

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error: SQLAlchemyError) -> tuple[Response, int]:
        get_uow().rollback()
        return _problem(503, "DATABASE_UNAVAILABLE", str(error))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": "td-service"}

    @app.get("/ready")
    def ready() -> tuple[Response, int] | dict[str, Any]:
        if runtime is None:
            return {"status": "ready", "dependencies": {"database": "memory-test-adapter"}}
        try:
            runtime.ready()
        except SQLAlchemyError:
            return _problem(503, "DATABASE_UNAVAILABLE", "Private database is not ready")
        return {"status": "ready", "dependencies": {"database": "ready"}}

    @app.get("/api/v1/projects/<uuid:project_id>/defects")
    def list_defects(project_id: UUID) -> dict[str, Any]:
        values = [
            _serialize(item)
            for (scope, _), item in get_uow().defects.items()
            if scope == project_id
        ]
        values.sort(key=lambda item: (item["business_no"], item["id"]))
        return {"data": values, "meta": {"count": len(values)}}

    @app.post("/api/v1/projects/<uuid:project_id>/defects")
    def create_defect(project_id: UUID) -> tuple[Response, int] | Response:
        actor_id = _actor_id()
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return _problem(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
        payload = request.get_json(silent=True) or {}
        digest = _request_hash(payload)
        store = get_uow()
        scope = (project_id, actor_id, key)
        prior = store.idempotency.get(scope)
        if prior is not None:
            if prior[0] != digest:
                return _problem(409, "IDEMPOTENCY_CONFLICT", "Key was already used with a different payload")
            return jsonify(prior[1]), prior[2]
        defect = get_service().create(actor_id, project_id, payload)
        body = {
            "data": _serialize(defect),
            "meta": {"trace_id": request.headers.get("X-Trace-Id", "local")},
        }
        store.idempotency[scope] = (digest, body, 201)
        store.commit()
        response = jsonify(body)
        response.status_code = 201
        response.headers["ETag"] = f'"{defect.version}"'
        return response

    @app.get("/api/v1/projects/<uuid:project_id>/defects/<uuid:defect_id>")
    def get_defect(project_id: UUID, defect_id: UUID) -> tuple[Response, int] | Response:
        defect = get_service().get(project_id, defect_id)
        if defect is None:
            return _problem(404, "RESOURCE_NOT_FOUND", "Defect is not visible")
        response = jsonify(data=_serialize(defect), meta={"trace_id": "local"})
        response.headers["ETag"] = f'"{defect.version}"'
        return response

    @app.post("/api/v1/projects/<uuid:project_id>/defects/<uuid:defect_id>/transitions")
    def transition_defect(project_id: UUID, defect_id: UUID) -> tuple[Response, int] | Response:
        actor_id = _actor_id()
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return _problem(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
        payload = request.get_json(silent=True) or {}
        digest = _request_hash(payload)
        store = get_uow()
        scope = (project_id, actor_id, key)
        prior = store.idempotency.get(scope)
        if prior is not None:
            if prior[0] != digest:
                return _problem(409, "IDEMPOTENCY_CONFLICT", "Key was already used with a different payload")
            return jsonify(prior[1]), prior[2]
        service = get_service()
        defect = service.get(project_id, defect_id)
        if defect is None:
            return _problem(404, "RESOURCE_NOT_FOUND", "Defect is not visible")
        if request.headers.get("If-Match") != f'"{defect.version}"':
            return _problem(412, "PRECONDITION_FAILED", "If-Match does not match the current ETag")
        fix = payload.get("fix_evidence")
        verification = payload.get("verification")
        updated = service.transition(
            actor_id,
            project_id,
            defect_id,
            action=str(payload.get("action", "")),
            privileged=bool(payload.get("privileged", False)),
            assignee_id=UUID(payload["assignee_id"]) if payload.get("assignee_id") else None,
            verifier_id=UUID(payload["verifier_id"]) if payload.get("verifier_id") else None,
            reason=str(payload.get("reason", "")),
            fix_version_id=UUID(payload["fix_version_id"]) if payload.get("fix_version_id") else None,
            fix_evidence=FixEvidence(**fix) if isinstance(fix, dict) else None,
            verification=VerificationEvidence(
                environment_ref=str(verification.get("environment_ref", "")),
                conclusion=str(verification.get("conclusion", "")),
                evidence_refs=tuple(map(str, verification.get("evidence_refs", []))),
            )
            if isinstance(verification, dict)
            else None,
            root_cause=str(payload.get("root_cause", "")),
            duplicate_of_id=UUID(payload["duplicate_of_id"])
            if payload.get("duplicate_of_id")
            else None,
        )
        body = {"data": _serialize(updated), "meta": {"trace_id": "local"}}
        store.idempotency[scope] = (digest, body, 200)
        store.commit()
        response = jsonify(body)
        response.headers["ETag"] = f'"{updated.version}"'
        return response

    @app.get("/api/v1/projects/<uuid:project_id>/defects/<uuid:defect_id>/history")
    def get_history(project_id: UUID, defect_id: UUID) -> tuple[Response, int] | dict[str, Any]:
        defect = get_service().get(project_id, defect_id)
        if defect is None:
            return _problem(404, "RESOURCE_NOT_FOUND", "Defect is not visible")
        return {"data": defect.history, "meta": {"count": len(defect.history)}}

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=18130)
