"""Flask API for TP library, design gates and safe XMind imports."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from flask import Flask, Response, g, jsonify, request
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.local import LocalProxy

from tp_service.config import Config
from tp_service.domain import DomainError
from tp_service.execution import ManagedEnvironment, PlanScopeSnapshot
from tp_service.repository import (
    AllowAllAuthorizer,
    MemoryUnitOfWork,
    SqlAlchemyRuntime,
)
from tp_service.service import TpService
from tp_service.traceability import TraceEndpoint, TraceGraph, TraceProjectionService


def _problem(status: int, code: str, detail: str) -> tuple[Response, int]:
    response = jsonify(type=f"urn:problem:{code.lower()}", title=code.replace("_", " ").title(), status=status, detail=detail, code=code)
    response.content_type = "application/problem+json"
    return response, status


def _actor_id() -> UUID:
    try:
        return UUID(request.headers.get("X-Actor-Id", ""))
    except ValueError as error:
        raise DomainError("UNAUTHENTICATED", "A valid actor identity is required", 401) from error


def _write_headers() -> tuple[UUID, str]:
    actor_id = _actor_id()
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required", 400)
    return actor_id, key


def _folder(folder: Any) -> dict[str, Any]:
    return {"id": str(folder.id), "project_id": str(folder.project_id), "name": folder.name, "parent_id": str(folder.parent_id) if folder.parent_id else None, "version": folder.version}


def _session(session: Any) -> dict[str, Any]:
    return {"id": str(session.id), "project_id": str(session.project_id), "status": session.status.value, "version": session.version, "target_folder_id": str(session.target_folder_id), "approved_stages": sorted(session.approved_stages), "runs": [{"id": str(run.id), "stage": run.stage, "attempt": run.attempt, "status": run.status, "provider": run.provider, "adapter_key": run.adapter_key, "input_hash": run.input_hash, "output_hash": run.output_hash} for run in session.runs]}


def _environment(environment: ManagedEnvironment) -> dict[str, Any]:
    return {
        "id": str(environment.id),
        "project_id": str(environment.project_id),
        "name": environment.name,
        "classification": environment.classification,
        "base_url": environment.base_url,
        "configuration_summary": environment.configuration_summary,
        "variable_keys": list(environment.variable_keys),
        "secret_ref_count": environment.secret_ref_count,
    }


def _plan(plan: Any) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "project_id": str(plan.project_id),
        "business_no": plan.business_no,
        "owner_id": str(plan.owner_id),
        "status": plan.status,
        "scope_hash": plan.scope_hash,
        "version": plan.version,
        "scope": [
            {
                "requirement_ref": str(item.requirement_ref),
                "requirement_revision": item.requirement_revision,
                "requirement_hash": item.requirement_hash,
                "case_version_ref": str(item.case_version_ref),
                "environment_id": str(item.environment_id),
            }
            for item in plan.scope
        ],
    }


def _execution(execution: Any) -> dict[str, Any]:
    aggregate = execution.aggregate
    return {
        "id": str(aggregate.id),
        "project_id": str(aggregate.project_id),
        "plan_id": str(aggregate.plan_id),
        "environment_id": str(aggregate.environment_id),
        "assignee_id": str(aggregate.assignee_id),
        "round_no": execution.round_no,
        "status": aggregate.status,
        "version": aggregate.version,
        "attempts": {
            str(case_ref): [
                {
                    "id": str(attempt.id),
                    "attempt_no": attempt.attempt_no,
                    "status": attempt.status,
                    "actual_result": attempt.actual_result,
                    "version": attempt.version,
                }
                for attempt in attempts
            ]
            for case_ref, attempts in aggregate.attempts.items()
        },
    }


def _trace_endpoint(endpoint: TraceEndpoint) -> dict[str, Any]:
    return {
        "project_id": str(endpoint.project_id),
        "domain": endpoint.domain,
        "resource_type": endpoint.resource_type,
        "resource_id": str(endpoint.resource_id),
        "revision": endpoint.revision,
    }


def _trace_graph(graph: TraceGraph) -> dict[str, Any]:
    return {
        "nodes": [_trace_endpoint(node) for node in graph.nodes],
        "links": [
            {
                "id": str(link.id),
                "source": _trace_endpoint(link.source),
                "target": _trace_endpoint(link.target),
                "link_type": link.link_type,
                "status": link.status,
            }
            for link in graph.links
        ],
        "truncated": graph.truncated,
        "stale": graph.stale,
        "broken": graph.broken,
        "completeness": graph.completeness,
    }


def create_app(
    uow: MemoryUnitOfWork | None = None,
    trace_projection: TraceProjectionService | None = None,
    config: Config | None = None,
) -> Flask:
    """Create an independently testable, production-safe TP HTTP adapter."""
    app = Flask(__name__)
    settings = config or Config.from_env()
    runtime: SqlAlchemyRuntime | None = None
    memory_store = uow
    if memory_store is None and settings.database_url:
        runtime = SqlAlchemyRuntime(
            create_engine(settings.database_url, pool_pre_ping=True)
        )
    elif memory_store is None:
        memory_store = MemoryUnitOfWork()

    def current_store() -> MemoryUnitOfWork:
        """Return the injected adapter or one SQL UoW per request context."""
        if memory_store is not None:
            return memory_store
        if "tp_uow" not in g:
            if runtime is None:
                raise RuntimeError("TP SQL runtime is not configured")
            g.tp_uow = runtime.unit_of_work()
        return g.tp_uow

    def current_service() -> TpService:
        """Create a service bound to the current transaction-scoped UoW."""
        if "tp_service" not in g:
            g.tp_service = TpService(current_store(), AllowAllAuthorizer())
        return g.tp_service

    store = LocalProxy(current_store)
    service = LocalProxy(current_service)
    traces = trace_projection or TraceProjectionService()
    app.extensions.update(
        tp_uow=memory_store,
        tp_runtime=runtime,
        tp_uow_factory=current_store,
    )

    @app.teardown_appcontext
    def close_session(error: BaseException | None) -> None:
        if runtime is None:
            return
        request_store = g.pop("tp_uow", None)
        g.pop("tp_service", None)
        if error is not None and request_store is not None:
            request_store.rollback()
        runtime.remove()

    def request_fingerprint(operation: str, payload: dict[str, Any]) -> str:
        """Hash the command input before any domain mutation occurs."""
        return hashlib.sha256(
            json.dumps(
                {"operation": operation, "payload": payload},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def replay_response(
        actor_id: UUID,
        project_id: UUID,
        key: str,
        fingerprint: str,
    ) -> tuple[Response, int] | None:
        """Replay a matching durable response or reject key reuse."""
        prior = store.idempotency.get((project_id, actor_id, key))
        if prior is None:
            return None
        if prior[0] != fingerprint:
            raise DomainError(
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency key was already used with another request",
                409,
            )
        return jsonify(prior[1]), prior[2]

    def commit_response(
        actor_id: UUID,
        project_id: UUID,
        key: str,
        fingerprint: str,
        payload: dict[str, Any],
        status: int,
    ) -> tuple[Response, int]:
        """Commit business state, response record and Outbox in one transaction."""
        body = {"data": payload, "meta": {"trace_id": "local"}}
        store.idempotency[(project_id, actor_id, key)] = (
            fingerprint,
            body,
            status,
        )
        store.commit()
        return jsonify(body), status

    @app.errorhandler(DomainError)
    def handle_domain(error: DomainError) -> tuple[Response, int]:
        return _problem(error.status, error.code, error.detail)

    @app.errorhandler(ValueError)
    def handle_value(error: ValueError) -> tuple[Response, int]:
        return _problem(422, "VALIDATION_ERROR", str(error))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": "tp-service"}

    @app.get("/ready")
    def ready() -> tuple[dict[str, Any], int] | dict[str, Any]:
        if runtime is None:
            return {
                "status": "ready",
                "dependencies": {
                    "database": "memory-test-adapter",
                    "ai": "deterministic-mock",
                },
            }
        try:
            runtime.ready()
        except SQLAlchemyError:
            return {
                "status": "not-ready",
                "dependencies": {"database": "unavailable"},
            }, 503
        return {
            "status": "ready",
            "dependencies": {"database": "ok", "ai": "deterministic-mock"},
        }

    @app.get("/api/v1/projects/<uuid:project_id>/test-folders")
    def list_folders(project_id: UUID) -> dict[str, Any]:
        values = [_folder(item) for (scope, _), item in store.folders.items() if scope == project_id]
        values.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        return {"data": values, "meta": {"count": len(values)}}

    @app.post("/api/v1/projects/<uuid:project_id>/test-folders")
    def create_folder(project_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint("test-folder:create", payload)
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        folder = service.create_folder(actor_id, project_id, str(payload.get("name", "")), UUID(payload["parent_id"]) if payload.get("parent_id") else None)
        response, status = commit_response(
            actor_id, project_id, key, fingerprint, _folder(folder), 201
        )
        response.headers["ETag"] = f'"{folder.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-folders/<uuid:folder_id>/move")
    def move_folder(project_id: UUID, folder_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint(
            "test-folder:move",
            {"folder_id": str(folder_id), **payload},
        )
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        folder = store.folders.get((project_id, folder_id))
        if folder is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Folder is not visible", 404)
        if request.headers.get("If-Match") != f'"{folder.version}"':
            raise DomainError("PRECONDITION_FAILED", "If-Match does not match the current ETag", 412)
        moved = service.move_folder(actor_id, project_id, folder_id, UUID(payload["target_parent_id"]) if payload.get("target_parent_id") else None)
        response, status = commit_response(
            actor_id, project_id, key, fingerprint, _folder(moved), 200
        )
        response.headers["ETag"] = f'"{moved.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-design-sessions")
    def create_design_session(project_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint("test-design-session:create", payload)
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        session = service.create_design_session(actor_id, project_id, tuple(map(str, payload.get("requirement_snapshot_refs", []))), UUID(str(payload.get("target_folder_id", ""))))
        response, status = commit_response(
            actor_id, project_id, key, fingerprint, _session(session), 201
        )
        response.headers["ETag"] = f'"{session.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-design-sessions/<uuid:session_id>/stage-runs")
    def run_stage(project_id: UUID, session_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint(
            "test-design-stage:run",
            {"session_id": str(session_id), **payload},
        )
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        current = service._session(project_id, session_id)
        if request.headers.get("If-Match") != f'"{current.version}"':
            raise DomainError("PRECONDITION_FAILED", "If-Match does not match the current ETag", 412)
        session = service.run_stage(actor_id, project_id, session_id, str(payload.get("stage", "")))
        response, status = commit_response(
            actor_id, project_id, key, fingerprint, _session(session), 200
        )
        response.headers["ETag"] = f'"{session.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-design-sessions/<uuid:session_id>/stage-runs/<uuid:run_id>/review-gates")
    def review_gate(project_id: UUID, session_id: UUID, run_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint(
            "test-design-gate:review",
            {"session_id": str(session_id), "run_id": str(run_id), **payload},
        )
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        current = service._session(project_id, session_id)
        if request.headers.get("If-Match") != f'"{current.version}"':
            raise DomainError("PRECONDITION_FAILED", "If-Match does not match the current ETag", 412)
        session = service.review_gate(
            actor_id,
            project_id,
            session_id,
            run_id,
            str(payload.get("decision", "")),
            bool(payload.get("privileged", False)),
            str(payload.get("comments", "")),
        )
        response, status = commit_response(
            actor_id, project_id, key, fingerprint, _session(session), 200
        )
        response.headers["ETag"] = f'"{session.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-design-sessions/<uuid:session_id>/imports")
    def import_xmind(project_id: UUID, session_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        upload = request.files.get("file")
        if upload is None:
            raise DomainError("XMIND_FILE_REQUIRED", "A multipart XMind file is required", 422)
        file_bytes = upload.stream.read(50 * 1024 * 1024 + 1)
        conflict_strategy = request.form.get("conflict_strategy", "create_new")
        fingerprint = request_fingerprint(
            "test-design:xmind-import",
            {
                "session_id": str(session_id),
                "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
                "conflict_strategy": conflict_strategy,
            },
        )
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        current = service._session(project_id, session_id)
        if request.headers.get("If-Match") != f'"{current.version}"':
            raise DomainError("PRECONDITION_FAILED", "If-Match does not match the current ETag", 412)
        batch = service.import_xmind(
            actor_id,
            project_id,
            session_id,
            file_bytes,
            conflict_strategy,
        )
        response, status = commit_response(
            actor_id, project_id, key, fingerprint, batch, 200
        )
        response.headers["ETag"] = f'"{current.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-environments")
    def create_environment(project_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint("test-environment:create", payload)
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        environment = ManagedEnvironment(
            uuid4(),
            project_id,
            str(payload.get("name", "")),
            str(payload.get("classification", "")),
            str(payload.get("base_url", "")),
            str(payload.get("configuration_summary", "")),
            tuple(map(str, payload.get("variable_keys", []))),
            int(payload.get("secret_ref_count", 0)),
        )
        created = service.create_environment(actor_id, project_id, environment)
        return commit_response(
            actor_id,
            project_id,
            key,
            fingerprint,
            _environment(created),
            201,
        )

    @app.post("/api/v1/projects/<uuid:project_id>/test-plans")
    def create_plan(project_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint("test-plan:create", payload)
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        plan = service.create_plan(
            actor_id,
            project_id,
            UUID(str(payload.get("owner_id", ""))),
            str(payload.get("business_no", "")),
        )
        response, status = commit_response(
            actor_id, project_id, key, fingerprint, _plan(plan), 201
        )
        response.headers["ETag"] = f'"{plan.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-plans/<uuid:plan_id>/freeze")
    def freeze_plan(project_id: UUID, plan_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint("test-plan:freeze", payload)
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        current = service._project_resource(store.plans, project_id, plan_id, "Test plan")
        if request.headers.get("If-Match") != f'"{current.version}"':
            raise DomainError(
                "PRECONDITION_FAILED",
                "If-Match does not match the current ETag",
                412,
            )
        scope = tuple(
            PlanScopeSnapshot(
                UUID(str(item["requirement_ref"])),
                int(item["requirement_revision"]),
                str(item["requirement_hash"]),
                UUID(str(item["case_version_ref"])),
                UUID(str(item["environment_id"])),
            )
            for item in payload.get("scope", [])
        )
        valid = {UUID(str(value)) for value in payload.get("valid_case_versions", [])}
        plan = service.freeze_plan(actor_id, project_id, plan_id, scope, valid)
        response, status = commit_response(
            actor_id, project_id, key, fingerprint, _plan(plan), 200
        )
        response.headers["ETag"] = f'"{plan.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-executions")
    def create_execution(project_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload = request.get_json(silent=True) or {}
        fingerprint = request_fingerprint("test-execution:create", payload)
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        execution = service.create_execution(
            actor_id,
            project_id,
            UUID(str(payload.get("plan_id", ""))),
            UUID(str(payload.get("environment_id", ""))),
            UUID(str(payload.get("assignee_id", ""))),
            int(payload.get("round_no", 1)),
        )
        response, status = commit_response(
            actor_id,
            project_id,
            key,
            fingerprint,
            _execution(execution),
            201,
        )
        response.headers["ETag"] = f'"{execution.aggregate.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/test-executions/<uuid:execution_id>/start")
    def start_execution(project_id: UUID, execution_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        payload: dict[str, Any] = {}
        fingerprint = request_fingerprint("test-execution:start", payload)
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        current = service._project_resource(
            store.executions, project_id, execution_id, "Execution"
        )
        if request.headers.get("If-Match") != f'"{current.aggregate.version}"':
            raise DomainError(
                "PRECONDITION_FAILED",
                "If-Match does not match the current ETag",
                412,
            )
        execution = service.start_execution(actor_id, project_id, execution_id)
        response, status = commit_response(
            actor_id,
            project_id,
            key,
            fingerprint,
            _execution(execution),
            200,
        )
        response.headers["ETag"] = f'"{execution.aggregate.version}"'
        return response, status

    @app.post("/api/v1/projects/<uuid:project_id>/automation-result-ingestions")
    def ingest_results(project_id: UUID) -> tuple[Response, int]:
        actor_id, key = _write_headers()
        raw_payload = request.get_data(cache=True)
        mapping_header = request.headers.get("X-Case-Mappings", "{}")
        command_payload = {
            "body_sha256": hashlib.sha256(raw_payload).hexdigest(),
            "case_mappings": json.loads(mapping_header),
            "content_type": request.content_type or "application/json",
            "source": request.headers.get("X-Result-Source", "junit"),
            "external_run_ref": request.headers.get("X-External-Run-Ref", ""),
        }
        fingerprint = request_fingerprint("automation-result:ingest", command_payload)
        prior = replay_response(actor_id, project_id, key, fingerprint)
        if prior is not None:
            return prior
        mappings = {
            str(name): UUID(str(case_id))
            for name, case_id in json.loads(mapping_header).items()
        }
        ingestion = service.ingest_results(
            actor_id,
            project_id,
            raw_payload,
            mappings,
            request.content_type or "application/json",
            request.headers.get("X-Result-Source", "junit"),
            request.headers.get("X-External-Run-Ref", ""),
        )
        data = {
            "id": str(ingestion.id),
            "project_id": str(ingestion.project_id),
            "source": ingestion.source,
            "external_run_ref": ingestion.external_run_ref,
            "payload_hash": ingestion.payload_hash,
            "summary": ingestion.summary,
        }
        return commit_response(
            actor_id,
            project_id,
            key,
            fingerprint,
            data,
            201,
        )

    @app.get("/api/v1/projects/<uuid:project_id>/traceability/<uuid:resource_id>")
    def query_trace(project_id: UUID, resource_id: UUID) -> dict[str, Any]:
        projection = traces
        if trace_projection is None:
            links = dict(store.traceability_links)
            projection = TraceProjectionService(
                links=links,
                consumed_events={link.source_event_id for link in links.values()},
                last_event_at=max(
                    (link.occurred_at for link in links.values()),
                    default=None,
                ),
            )
        graph = projection.query(
            project_id,
            resource_id,
            request.args.get("direction", "both"),
            request.args.get("depth", default=4, type=int),
            request.args.get("limit", default=500, type=int),
        )
        return {"data": _trace_graph(graph), "meta": {"trace_id": "local"}}

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=18120)
