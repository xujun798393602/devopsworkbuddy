"""Flask API for the requirement service."""
from __future__ import annotations

import base64
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
from requirement_service.service import (
    CHANGE_REQUEST_ACTIONS,
    REASON_REQUIRED_ACTIONS,
    REQUIREMENT_ACTIONS,
    REQUIREMENT_LIST_LIMIT_DEFAULT,
    REQUIREMENT_LIST_LIMIT_MAX,
    REVIEW_DECISIONS,
    PORTAL_REVIEW_LIMIT_DEFAULT,
    PORTAL_REVIEW_LIMIT_MAX,
    RequirementService,
    UnitOfWork,
)

PORTAL_CROSS_PROJECT_PERMISSION = "portal:cross-project-view"


def portal_cross_project(headers: Any) -> bool:
    """Resolve the effective cross-project flag with defence in depth.

    The gateway already decided, but this service re-checks the injected
    permission set so a forged ``X-Portal-Cross-Project`` header alone can never
    widen the data scope.
    """
    if headers.get("X-Portal-Cross-Project", "").strip().lower() != "true":
        return False
    granted = {
        item.strip() for item in headers.get("X-Platform-Permissions", "").split(",") if item.strip()
    }
    return PORTAL_CROSS_PROJECT_PERMISSION in granted


def parse_project_ids(raw: str | None) -> tuple[str, ...]:
    """Parse the CSV project scope, dropping malformed identifiers."""
    if not raw:
        return ()
    scope: list[str] = []
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            scope.append(str(UUID(candidate)))
        except ValueError:
            continue
    return tuple(dict.fromkeys(scope))


def parse_portal_limit(raw: str | None, default: int, maximum: int) -> int:
    """Parse a bounded portal limit, raising ``ValueError`` when out of range."""
    if raw is None or raw == "":
        return default
    limit = int(raw)
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return limit


def problem(status: int, code: str, detail: str, *, trace_id: str | None = None) -> Response:
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
    response.status_code = status
    response.content_type = "application/problem+json"
    return response


def _trace_id() -> str:
    """Return the gateway-supplied trace id or a local placeholder."""
    return request.headers.get("X-Trace-Id", "local")


def _actor_id() -> UUID | None:
    """Resolve the gateway-injected actor identity or ``None`` when absent."""
    raw = request.headers.get("X-Actor-Id", "")
    try:
        return UUID(raw)
    except ValueError:
        return None


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
        return problem(error.status, error.code, error.detail, trace_id=_trace_id())

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
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        response = jsonify(body)
        response.status_code = 201
        response.headers["ETag"] = '"1"'
        return response

    @app.get("/api/v1/projects/<uuid:project_id>/requirements")
    def list_requirements(project_id: UUID) -> Response:
        """Cursor-paginated requirement list (architecture §9.A.1)."""
        try:
            limit = parse_portal_limit(
                request.args.get("limit"),
                REQUIREMENT_LIST_LIMIT_DEFAULT,
                REQUIREMENT_LIST_LIMIT_MAX,
            )
        except ValueError as error:
            return problem(422, "VALIDATION_ERROR", str(error))
        offset = _decode_cursor(request.args.get("cursor"))
        # Request one extra row so we can decide whether another page exists
        # without a second query.
        rows = service.list_requirements(project_id, offset=offset, limit=limit + 1)
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = _encode_cursor(offset + limit) if has_more else None
        return jsonify(
            data={"items": [_requirement_data(item) for item in items]},
            meta={
                "next_cursor": next_cursor,
                "has_more": has_more,
                "trace_id": _trace_id(),
            },
        )

    @app.get("/api/v1/projects/<uuid:project_id>/requirements/<uuid:requirement_id>")
    def get_requirement(project_id: UUID, requirement_id: UUID) -> Response:
        value = service.get(project_id, requirement_id)
        if value is None:
            return problem(404, "RESOURCE_NOT_FOUND", "Requirement is not visible")
        response = jsonify(
            data=_requirement_data(value),
            meta={"trace_id": _trace_id()},
        )
        response.headers["ETag"] = f'"{value.version}"'
        return response

    @app.patch("/api/v1/projects/<uuid:project_id>/requirements/<uuid:requirement_id>")
    def patch_requirement(project_id: UUID, requirement_id: UUID) -> Response:
        """Optimistic-concurrency update (architecture §9.A.2)."""
        actor_id = _actor_id()
        if actor_id is None:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        current = service.get(project_id, requirement_id)
        if current is None:
            return problem(404, "RESOURCE_NOT_FOUND", "Requirement is not visible")
        if request.headers.get("If-Match") != f'"{current.version}"':
            return problem(
                412,
                "PRECONDITION_FAILED",
                "If-Match does not match the current version",
            )
        changes = request.get_json(silent=True) or {}
        try:
            requirement, change = service.patch(
                actor_id, project_id, requirement_id, changes
            )
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        body = requirement_detail(requirement, change)
        store.commit()
        response = jsonify(body)
        response.headers["ETag"] = f'"{requirement.version}"'
        return response

    @app.post(
        "/api/v1/projects/<uuid:project_id>/requirements/<uuid:requirement_id>/transitions"
    )
    def transition_requirement(project_id: UUID, requirement_id: UUID) -> Response:
        """Apply one explicit lifecycle action (architecture §9.A.3)."""
        actor_id = _actor_id()
        if actor_id is None:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        if action not in REQUIREMENT_ACTIONS:
            return problem(
                422,
                "INVALID_TRANSITION_ACTION",
                f"Unsupported action: {action!r}",
            )
        reason = str(payload.get("reason", ""))
        if action in REASON_REQUIRED_ACTIONS and not reason.strip():
            return problem(
                422,
                "REASON_REQUIRED",
                "reason is required for this action",
            )
        current = service.get(project_id, requirement_id)
        if current is None:
            return problem(404, "RESOURCE_NOT_FOUND", "Requirement is not visible")
        if request.headers.get("If-Match") != f'"{current.version}"':
            return problem(
                412,
                "PRECONDITION_FAILED",
                "If-Match does not match the current version",
            )
        try:
            requirement = service.transition(
                actor_id,
                project_id,
                requirement_id,
                action=action,
                approved_review=bool(payload.get("approved_review", False)),
                baselined=bool(payload.get("baselined", False)),
                completion_evidence=bool(payload.get("completion_evidence", False)),
                privileged=bool(payload.get("privileged", False)),
                reason=reason,
            )
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        body = requirement_detail(requirement)
        store.commit()
        response = jsonify(body)
        response.headers["ETag"] = f'"{requirement.version}"'
        return response

    @app.post(
        "/api/v1/projects/<uuid:project_id>/requirements/<uuid:requirement_id>/reviews"
    )
    def create_review(project_id: UUID, requirement_id: UUID) -> Response:
        """Open a review round against the latest frozen revision (§9.A.4)."""
        actor_id = _actor_id()
        if actor_id is None:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        payload = request.get_json(silent=True) or {}
        try:
            reviewer_ids = tuple(
                UUID(str(item)) for item in payload.get("reviewer_ids", [])
            )
        except ValueError as error:
            return problem(422, "VALIDATION_ERROR", str(error))
        note = str(payload.get("note", ""))
        try:
            review = service.create_review(
                actor_id,
                project_id,
                requirement_id,
                reviewer_ids=reviewer_ids,
                note=note,
            )
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        body = review_body(review)
        store.commit()
        response = jsonify(body)
        response.status_code = 201
        return response

    @app.post(
        "/api/v1/projects/<uuid:project_id>/requirements/<uuid:requirement_id>"
        "/reviews/<uuid:review_id>/decisions"
    )
    def decide_review(
        project_id: UUID, requirement_id: UUID, review_id: UUID
    ) -> Response:
        """Append one reviewer decision (architecture §9.A.4)."""
        actor_id = _actor_id()
        if actor_id is None:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        payload = request.get_json(silent=True) or {}
        reviewer_id_raw = payload.get("reviewer_id")
        if reviewer_id_raw is None:
            return problem(422, "VALIDATION_ERROR", "reviewer_id is required")
        try:
            reviewer_id = UUID(str(reviewer_id_raw))
        except ValueError as error:
            return problem(422, "VALIDATION_ERROR", str(error))
        decision = payload.get("decision")
        if decision not in REVIEW_DECISIONS:
            return problem(
                422,
                "INVALID_REVIEW_DECISION",
                f"Unsupported decision: {decision!r}",
            )
        comments = str(payload.get("comments", ""))
        try:
            review = service.decide_review(
                actor_id,
                project_id,
                requirement_id,
                review_id,
                reviewer_id=reviewer_id,
                decision=decision,
                comments=comments,
            )
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        body = review_body(review)
        store.commit()
        return jsonify(body)

    @app.post("/api/v1/projects/<uuid:project_id>/requirement-baselines")
    def create_baseline(project_id: UUID) -> Response:
        """Create a draft baseline snapshot (architecture §9.A.5)."""
        actor_id = _actor_id()
        if actor_id is None:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        payload = request.get_json(silent=True) or {}
        try:
            release_version_id = UUID(str(payload["release_version_id"]))
        except (KeyError, ValueError) as error:
            return problem(422, "VALIDATION_ERROR", str(error))
        revision_refs = tuple(
            (UUID(str(item["requirement_id"])), str(item["revision_no"]))
            for item in payload.get("revision_refs", [])
        )
        try:
            baseline = service.create_baseline(
                actor_id,
                project_id,
                baseline_no=str(payload.get("baseline_no", "")),
                release_version_id=release_version_id,
                revision_refs=revision_refs,
            )
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        body = baseline_body(baseline)
        store.commit()
        response = jsonify(body)
        response.status_code = 201
        return response

    @app.post(
        "/api/v1/projects/<uuid:project_id>/requirement-baselines/<uuid:baseline_id>/activate"
    )
    def activate_baseline(project_id: UUID, baseline_id: UUID) -> Response:
        """Activate a draft baseline exactly once (architecture §9.A.5)."""
        actor_id = _actor_id()
        if actor_id is None:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        try:
            baseline = service.activate_baseline(actor_id, project_id, baseline_id)
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        body = baseline_body(baseline)
        store.commit()
        return jsonify(body)

    @app.post(
        "/api/v1/projects/<uuid:project_id>/requirements/<uuid:requirement_id>/change-requests"
    )
    def create_change_request(project_id: UUID, requirement_id: UUID) -> Response:
        """Open a governed change request against a frozen revision (§9.A.6)."""
        actor_id = _actor_id()
        if actor_id is None:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        payload = request.get_json(silent=True) or {}
        try:
            base_revision_id = UUID(str(payload["base_revision_id"]))
        except (KeyError, ValueError) as error:
            return problem(422, "VALIDATION_ERROR", str(error))
        proposed_patch = payload.get("proposed_patch", {})
        try:
            change = service.create_change_request(
                actor_id,
                project_id,
                requirement_id,
                base_revision_id=base_revision_id,
                proposed_patch=proposed_patch,
            )
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        body = change_request_body(change)
        store.commit()
        response = jsonify(body)
        response.status_code = 201
        return response

    @app.post(
        "/api/v1/projects/<uuid:project_id>/requirements/<uuid:requirement_id>"
        "/change-requests/<uuid:change_request_id>/transitions"
    )
    def transition_change_request(
        project_id: UUID, requirement_id: UUID, change_request_id: UUID
    ) -> Response:
        """Advance a change request through its governance state machine (§9.A.6)."""
        actor_id = _actor_id()
        if actor_id is None:
            return problem(401, "UNAUTHENTICATED", "A valid actor identity is required")
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        if action not in CHANGE_REQUEST_ACTIONS:
            return problem(
                422,
                "INVALID_CHANGE_REQUEST_ACTION",
                f"Unsupported action: {action!r}",
            )
        try:
            change, _requirement = service.transition_change_request(
                actor_id,
                project_id,
                requirement_id,
                change_request_id,
                action=action,
            )
        except DomainError:
            raise
        except (KeyError, ValueError) as error:
            store.rollback()
            return problem(422, "VALIDATION_ERROR", str(error))
        body = change_request_body(change)
        store.commit()
        return jsonify(body)

    @app.get("/api/v1/portal/requirement-summary")
    def portal_requirement_summary() -> Response:
        """Return the batched requirement statistics block for the portal."""
        try:
            review_limit = parse_portal_limit(
                request.args.get("review_limit"),
                PORTAL_REVIEW_LIMIT_DEFAULT,
                PORTAL_REVIEW_LIMIT_MAX,
            )
        except ValueError as error:
            return problem(422, "VALIDATION_ERROR", str(error))
        data = service.portal_summary(
            parse_project_ids(request.args.get("project_ids")),
            request.headers.get("X-Actor-Id") or None,
            cross_project=portal_cross_project(request.headers),
            review_limit=review_limit,
        )
        return jsonify(data=data, meta={"trace_id": _trace_id()})

    return app


def _requirement_data(value: Requirement) -> dict[str, Any]:
    """Serialize the full requirement content for list and detail responses.

    ``created_at``/``updated_at`` are ``None`` because the aggregate and the
    persistence row intentionally carry no timestamp columns yet; adding them
    would require a schema migration, which this round explicitly excludes.
    TODO(P1): populate these from DB columns once the migration lands.
    """
    return {
        "id": str(value.id),
        "project_id": str(value.project_id),
        "business_no": value.business_no,
        "title": value.title,
        "type": value.type.value,
        "status": value.status.value,
        "priority": value.priority,
        "owner_id": str(value.owner_id),
        "release_version_id": str(value.release_version_id),
        "parent_id": str(value.parent_id) if value.parent_id else None,
        "description": value.description,
        "acceptance_criteria": value.acceptance_criteria,
        "current_revision": value.current_revision,
        "baseline_status": value.baseline_status,
        "version": value.version,
        "created_at": None,
        "updated_at": None,
    }


def requirement_detail(
    value: Requirement, change_request: Any = None
) -> dict[str, Any]:
    """Serialize a single requirement, optionally surfacing a created change request."""
    body: dict[str, Any] = {
        "data": _requirement_data(value),
        "meta": {"trace_id": _trace_id()},
    }
    if change_request is not None:
        body["data"]["change_request"] = {
            "id": str(change_request.id),
            "status": change_request.status,
            "version": change_request.version,
        }
    return body


def review_body(value: Any) -> dict[str, Any]:
    """Serialize a review round."""
    return {
        "data": {
            "id": str(value.id),
            "round_no": value.round_no,
            "revision_id": str(value.revision_id),
            "submitted_by": str(value.submitted_by),
            "reviewer_ids": [str(item) for item in value.reviewer_ids],
            "status": value.status,
            "decisions": value.decisions,
        },
        "meta": {"trace_id": _trace_id()},
    }


def baseline_body(value: Any) -> dict[str, Any]:
    """Serialize a baseline snapshot."""
    return {
        "data": {
            "id": str(value.id),
            "project_id": str(value.project_id),
            "baseline_no": value.baseline_no,
            "release_version_id": str(value.release_version_id),
            "revision_refs": [
                [str(item[0]), item[1]] for item in value.revision_refs
            ],
            "status": value.status,
            "version": value.version,
        },
        "meta": {"trace_id": _trace_id()},
    }


def change_request_body(value: Any) -> dict[str, Any]:
    """Serialize a change request."""
    return {
        "data": {
            "id": str(value.id),
            "requirement_id": str(value.requirement_id),
            "base_revision_id": str(value.base_revision_id),
            "proposed_patch": value.proposed_patch,
            "status": value.status,
            "version": value.version,
        },
        "meta": {"trace_id": _trace_id()},
    }


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
        "meta": {"trace_id": _trace_id()},
    }


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=18110)
