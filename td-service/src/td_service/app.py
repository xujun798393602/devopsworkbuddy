"""Flask HTTP adapter for the defect service."""
from __future__ import annotations

import base64
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
    MemoryPortalRepository,
    MemoryUnitOfWork,
    SqlAlchemyRuntime,
)
from td_service.service import (
    DEFECT_LIST_LIMIT_DEFAULT,
    DEFECT_LIST_LIMIT_MAX,
    PORTAL_DEFECT_LIMIT_DEFAULT,
    PORTAL_DEFECT_LIMIT_MAX,
    DefectService,
    PortalRepository,
    TdPortalService,
    UnitOfWork,
)

PORTAL_CROSS_PROJECT_PERMISSION = "portal:cross-project-view"


def optional_actor_id(raw: str | None) -> UUID | None:
    """Parse the gateway-injected actor identity without failing a read."""
    if not raw:
        return None
    try:
        return UUID(raw.strip())
    except ValueError:
        return None


def platform_permissions(raw: str | None) -> frozenset[str]:
    """Parse the CSV permission header injected by the API gateway."""
    return frozenset(item.strip() for item in (raw or "").split(",") if item.strip())


def portal_cross_project(headers: Any) -> bool:
    """Re-validate the cross-project intent inside the domain (defence in depth).

    The gateway is the authoritative decision point, but a domain service must
    never widen its scope on the strength of ``X-Portal-Cross-Project`` alone.
    """
    requested = str(headers.get("X-Portal-Cross-Project", "")).strip().lower() == "true"
    if not requested:
        return False
    return PORTAL_CROSS_PROJECT_PERMISSION in platform_permissions(
        headers.get("X-Platform-Permissions")
    )


def parse_project_ids(raw: str | None) -> tuple[UUID, ...]:
    """Parse the ``project_ids`` CSV, dropping malformed and duplicated entries."""
    values: list[UUID] = []
    for item in (raw or "").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            values.append(UUID(candidate))
        except ValueError:
            continue
    return tuple(dict.fromkeys(values))


def parse_portal_limit(raw: str | None, default: int, maximum: int) -> int:
    """Parse a bounded portal list limit; out-of-range values raise ``ValueError``."""
    if raw is None or raw == "":
        return default
    limit = int(raw)
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return limit


def _problem(status: int, code: str, detail: str, *, trace_id: str | None = None) -> tuple[Response, int]:
    """Return an RFC 9457 problem response aligned with ``common.yaml``.

    ``error_code`` mirrors ``code`` for compatibility; ``trace_id`` is attached
    when the caller can supply one.
    """
    body: dict[str, Any] = {
        "type": f"urn:problem:{code.lower()}",
        "title": code.replace("_", " ").title(),
        "status": status,
        "detail": detail,
        "code": code,
        "error_code": code,
    }
    if trace_id is not None:
        body["trace_id"] = trace_id
    response = jsonify(body)
    response.content_type = "application/problem+json"
    return response, status


def _encode_cursor(offset: int) -> str:
    """Encode an opaque pagination cursor from a row offset."""
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _decode_cursor(raw: str | None) -> int:
    """Decode an opaque pagination cursor, defaulting to the first page."""
    if not raw:
        return 0
    try:
        return int(base64.urlsafe_b64decode(raw.encode("ascii")).decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return 0


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

    def get_portal_repository() -> PortalRepository:
        """Return a read-only portal projection for the current request.

        In SQL mode this deliberately avoids ``get_uow()`` because the defect
        unit of work eagerly hydrates every aggregate, which a dashboard summary
        must never pay for.
        """
        if memory_store is not None:
            return MemoryPortalRepository(cast(MemoryUnitOfWork, memory_store))
        if runtime is None:
            raise RuntimeError("TD SQL runtime is not configured")
        if "td_portal_repository" not in g:
            g.td_portal_repository = runtime.portal_repository()
        return cast(PortalRepository, g.td_portal_repository)

    @app.teardown_appcontext
    def close_session(error: BaseException | None) -> None:
        if runtime is None:
            return
        current = g.pop("td_uow", None)
        g.pop("td_portal_repository", None)
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

    @app.get("/api/v1/portal/td-summary")
    def portal_td_summary() -> tuple[Response, int] | dict[str, Any]:
        """Return batched defect statistics for the platform dashboard.

        The ``/api/v1/portal/*`` prefix is not routable through the browser-facing
        gateway proxy, so this endpoint is only reachable server to server.
        """
        try:
            defect_limit = parse_portal_limit(
                request.args.get("defect_limit"),
                PORTAL_DEFECT_LIMIT_DEFAULT,
                PORTAL_DEFECT_LIMIT_MAX,
            )
        except ValueError as error:
            return _problem(422, "VALIDATION_ERROR", str(error))
        data = TdPortalService(get_portal_repository()).summary(
            parse_project_ids(request.args.get("project_ids")),
            optional_actor_id(request.headers.get("X-Actor-Id")),
            cross_project=portal_cross_project(request.headers),
            defect_limit=defect_limit,
        )
        return {
            "data": data,
            "meta": {"trace_id": request.headers.get("X-Trace-Id", "local")},
        }

    @app.get("/api/v1/projects/<uuid:project_id>/defects")
    def list_defects(project_id: UUID) -> dict[str, Any]:
        """Cursor-paginated defect list (architecture §9.B.1)."""
        try:
            limit = parse_portal_limit(
                request.args.get("limit"),
                DEFECT_LIST_LIMIT_DEFAULT,
                DEFECT_LIST_LIMIT_MAX,
            )
        except ValueError as error:
            return _problem(422, "VALIDATION_ERROR", str(error))
        offset = _decode_cursor(request.args.get("cursor"))
        # Request one extra row so we can decide whether another page exists
        # without a second query.
        rows = get_uow().list_defects(project_id, offset, limit + 1)
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = _encode_cursor(offset + limit) if has_more else None
        return {
            "data": {"items": [_serialize(item) for item in items]},
            "meta": {
                "next_cursor": next_cursor,
                "has_more": has_more,
                "trace_id": request.headers.get("X-Trace-Id", "local"),
            },
        }

    @app.patch("/api/v1/projects/<uuid:project_id>/defects/<uuid:defect_id>")
    def patch_defect(project_id: UUID, defect_id: UUID) -> tuple[Response, int] | Response:
        """Optimistic-concurrency defect update (architecture §9.B.2)."""
        actor_id = _actor_id()
        store = get_uow()
        defect = get_service().get(project_id, defect_id)
        if defect is None:
            return _problem(404, "RESOURCE_NOT_FOUND", "Defect is not visible")
        if request.headers.get("If-Match") != f'"{defect.version}"':
            return _problem(412, "PRECONDITION_FAILED", "If-Match does not match the current ETag")
        changes = request.get_json(silent=True) or {}
        try:
            updated = get_service().patch(actor_id, project_id, defect_id, changes)
        except (KeyError, ValueError) as error:
            store.rollback()
            return _problem(422, "VALIDATION_ERROR", str(error))
        body = {"data": _serialize(updated), "meta": {"trace_id": "local"}}
        store.commit()
        response = jsonify(body)
        response.headers["ETag"] = f'"{updated.version}"'
        return response

    @app.get("/api/v1/projects/<uuid:project_id>/defects/<uuid:defect_id>/traceability-links")
    def get_traceability_links(project_id: UUID, defect_id: UUID) -> dict[str, Any]:
        """Return the requirement/test-case traceability graph (§9.B.3)."""
        links = get_service().get_traceability_links(project_id, defect_id)
        return {
            "data": links,
            "meta": {"trace_id": request.headers.get("X-Trace-Id", "local")},
        }

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
