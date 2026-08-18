"""Workflow Flask API using explicit persistence and authorization ports."""
from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from flask import Flask, Response, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from workflow_service.integrations.project_authorization import (
    ControlledAuthorizer,
    ProjectAuthorizationPort,
)
from workflow_service.persistence import DatabaseSettings, SqlAlchemyRuntime
from workflow_service.workflows.models import WorkflowInstance, WorkflowTemplateVersion
from workflow_service.workflows.repository import (
    PORTAL_APPROVAL_LIMIT_DEFAULT,
    PORTAL_APPROVAL_LIMIT_MAX,
    InMemoryWorkflowRepository,
    MemoryPortalRepository,
    PortalRepository,
    WorkflowRepository,
)
from workflow_service.workflows.service import WorkflowPortalService, WorkflowService


def create_app(
    repo: WorkflowRepository | None = None,
    authorizer: ProjectAuthorizationPort | None = None,
    settings: DatabaseSettings | None = None,
) -> Flask:
    """Create the workflow application with production-safe adapter selection."""
    app = Flask(__name__)
    configured = settings or DatabaseSettings.from_env()
    runtime: SqlAlchemyRuntime | None = None
    if repo is not None:
        repository = repo
    elif configured.database_url:
        runtime = SqlAlchemyRuntime(configured.database_url)
        repository = runtime.repository()
    else:
        repository = InMemoryWorkflowRepository()
    authorization = authorizer or ControlledAuthorizer(set())
    service = WorkflowService(repository, authorization)
    app.extensions.update(
        workflow_repository=repository,
        workflow_service=service,
        workflow_runtime=runtime,
    )

    @app.before_request
    def trace() -> None:
        g.trace_id = request.headers.get("X-Trace-Id", str(uuid4()))

    @app.after_request
    def trace_header(response: Response) -> Response:
        response.headers["X-Trace-Id"] = g.trace_id
        return response

    @app.teardown_appcontext
    def close_session(error: BaseException | None) -> None:
        if runtime is None:
            return
        if error is not None:
            runtime.rollback()
        runtime.remove()

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok", "service": "workflow-service"})

    @app.get("/ready")
    def ready() -> tuple[Response, int] | Response:
        if runtime is None:
            return jsonify(
                {"status": "ready", "checks": {"repository": "in-memory"}}
            )
        try:
            runtime.ready()
        except SQLAlchemyError:
            return jsonify(
                {"status": "not-ready", "checks": {"database": "unavailable"}}
            ), 503
        return jsonify({"status": "ready", "checks": {"database": "ok"}})

    @app.post("/api/v1/workflow-templates")
    def create_template() -> tuple[Response, int] | tuple[Response, int, dict[str, str]]:
        denied = require_permission("workflow.template.manage")
        if denied:
            return denied
        body = request.get_json(silent=True) or {}
        key = str(body.get("template_key", ""))
        version = int(body.get("version", 1))
        if not key or repository.template(key, version):
            return problem(409, "TEMPLATE_EXISTS", "Template version already exists")
        item = WorkflowTemplateVersion(
            key,
            version,
            str(body.get("name", key)),
            dict(body.get("definition", {})),
        )
        repository.save_template(item)
        repository.append_outbox(
            {
                "event_type": "Workflow.TemplateDrafted",
                "data": {"template_key": key, "version": version},
            }
        )
        commit(runtime)
        return success(template_data(item)), 201

    @app.post("/api/v1/workflow-templates/<key>/versions/<int:version>/publish")
    def publish_template(
        key: str, version: int
    ) -> tuple[Response, int, dict[str, str]] | Response:
        denied = require_permission("workflow.template.manage")
        if denied:
            return denied
        item = repository.template(key, version)
        if item is None:
            return problem(404, "NOT_FOUND", "Template not found")
        try:
            item.publish()
        except ValueError as error:
            return problem(409, "INVALID_TEMPLATE_STATUS", str(error))
        repository.save_template(item)
        repository.append_outbox(
            {
                "event_type": "Workflow.TemplatePublished",
                "data": {"template_key": key, "version": version},
            }
        )
        commit(runtime)
        return success(template_data(item))

    @app.post("/api/v1/workflow-templates/<key>/versions/<int:version>/deprecate")
    def deprecate_template(
        key: str, version: int
    ) -> tuple[Response, int, dict[str, str]] | Response:
        denied = require_permission("workflow.template.manage")
        if denied:
            return denied
        item = repository.template(key, version)
        if item is None:
            return problem(404, "NOT_FOUND", "Template not found")
        try:
            item.deprecate()
        except ValueError as error:
            return problem(409, "INVALID_TEMPLATE_STATUS", str(error))
        repository.save_template(item)
        repository.append_outbox(
            {
                "event_type": "Workflow.TemplateDeprecated",
                "data": {"template_key": key, "version": version},
            }
        )
        commit(runtime)
        return success(template_data(item))

    @app.get("/api/v1/workflow-instances")
    def list_instances() -> Response:
        actor = request.headers.get("X-Actor-Id", "")
        project = request.args.get("project_id", "")
        visible = [
            instance_data(item)
            for item in repository.list_instances(project)
            if authorization.check(
                actor,
                project,
                "workflow.read",
                {"type": item.business_object_type, "id": item.business_object_id},
            )
        ]
        return success(visible)

    @app.post("/api/v1/workflow-instances")
    def start_instance() -> tuple[Response, int] | tuple[Response, int, dict[str, str]]:
        key = request.headers.get("Idempotency-Key", "")
        actor = request.headers.get("X-Actor-Id", "")
        if not key:
            return problem(
                422,
                "IDEMPOTENCY_KEY_REQUIRED",
                "Idempotency-Key is required",
            )
        try:
            item = service.start(request.get_json(silent=True) or {}, actor, key)
            commit(runtime)
        except PermissionError:
            rollback(runtime)
            return problem(403, "PROJECT_SCOPE_DENIED", "Project authorization denied")
        except (KeyError, ValueError) as error:
            rollback(runtime)
            return problem(422, "VALIDATION_FAILED", str(error))
        except RuntimeError as error:
            rollback(runtime)
            return problem(409, str(error), str(error))
        return success(instance_data(item)), 201

    @app.get("/api/v1/workflow-instances/<instance_id>")
    def get_instance(instance_id: str) -> tuple[Response, int, dict[str, str]] | Response:
        item = repository.instance(instance_id)
        actor = request.headers.get("X-Actor-Id", "")
        if item is None or not authorization.check(
            actor,
            item.project_id,
            "workflow.read",
            {"type": item.business_object_type, "id": item.business_object_id},
        ):
            return problem(404, "NOT_FOUND", "Workflow instance not found")
        return success(instance_data(item))

    @app.get("/api/v1/workflow-instances/<instance_id>/available-transitions")
    def available_transitions(
        instance_id: str,
    ) -> tuple[Response, int, dict[str, str]] | Response:
        item = repository.instance(instance_id)
        actor = request.headers.get("X-Actor-Id", "")
        if item is None or not authorization.check(
            actor,
            item.project_id,
            "workflow.read",
            {"type": item.business_object_type, "id": item.business_object_id},
        ):
            return problem(404, "NOT_FOUND", "Workflow instance not found")
        template = repository.template(item.template_key, item.template_version)
        transitions = (
            [
                entry
                for entry in template.definition["transitions"]
                if entry["from"] == item.current_state
            ]
            if template
            else []
        )
        return success(transitions)

    @app.post("/api/v1/workflow-instances/<instance_id>/transitions")
    def transition(
        instance_id: str,
    ) -> tuple[Response, int, dict[str, str]] | Response:
        actor = request.headers.get("X-Actor-Id", "")
        key = request.headers.get("Idempotency-Key", "")
        expected = parse_if_match(request.headers.get("If-Match"))
        if not key or expected is None:
            return problem(
                428,
                "PRECONDITION_REQUIRED",
                "Idempotency-Key and If-Match are required",
            )
        body = request.get_json(silent=True) or {}
        try:
            item = service.transition(
                instance_id,
                str(body.get("action", "")),
                actor,
                body.get("reason"),
                expected,
                key,
            )
            commit(runtime)
        except LookupError:
            rollback(runtime)
            return problem(404, "NOT_FOUND", "Workflow instance not found")
        except PermissionError:
            rollback(runtime)
            return problem(403, "PROJECT_SCOPE_DENIED", "Project authorization denied")
        except ValueError as error:
            rollback(runtime)
            return problem(409, str(error), str(error))
        except RuntimeError as error:
            rollback(runtime)
            status = 412 if str(error) == "VERSION_CONFLICT" else 409
            return problem(status, str(error), str(error))
        return success(instance_data(item))

    def get_portal_repository() -> PortalRepository:
        """Resolve the portal read repository for the active storage backend."""
        if isinstance(repository, InMemoryWorkflowRepository):
            return MemoryPortalRepository(repository)
        if runtime is not None:
            return runtime.portal_repository()
        return MemoryPortalRepository(repository)

    @app.get("/api/v1/portal/pending-approvals")
    def portal_pending_approvals() -> dict[str, object] | tuple[Response, int, dict[str, str]]:
        """Return batched workflow pending-approvals for the platform dashboard.

        The ``/api/v1/portal/*`` prefix is not routable through the
        browser-facing gateway proxy, so this endpoint is only reachable
        server to server.
        """
        try:
            limit = parse_portal_limit(
                request.args.get("limit"),
                PORTAL_APPROVAL_LIMIT_DEFAULT,
                PORTAL_APPROVAL_LIMIT_MAX,
            )
        except ValueError:
            return problem(
                422,
                "INVALID_LIMIT",
                f"limit must be between 1 and {PORTAL_APPROVAL_LIMIT_MAX}",
            )
        data = WorkflowPortalService(get_portal_repository()).summary(
            parse_project_ids(request.args.get("project_ids")),
            optional_actor_id(request.headers.get("X-Actor-Id")),
            cross_project=portal_cross_project(request.headers),
            limit=limit,
        )
        return success(data)

    return app


PORTAL_CROSS_PROJECT_PERMISSION = "portal:cross-project-view"


def optional_actor_id(raw: str | None) -> str | None:
    """Parse the gateway-injected actor identity without failing a read."""
    return raw.strip() if raw else None


def platform_permissions(raw: str | None) -> frozenset[str]:
    """Parse the CSV permission header injected by the API gateway."""
    return frozenset(item.strip() for item in (raw or "").split(",") if item.strip())


def portal_cross_project(headers: dict[str, str]) -> bool:
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


def parse_project_ids(raw: str | None) -> tuple[str, ...]:
    """Parse the ``project_ids`` CSV, dropping empty and duplicated entries."""
    values: list[str] = []
    for item in (raw or "").split(","):
        candidate = item.strip()
        if candidate and candidate not in values:
            values.append(candidate)
    return tuple(values)


def parse_portal_limit(raw: str | None, default: int, maximum: int) -> int:
    """Parse a bounded portal list limit; out-of-range values raise ``ValueError``."""
    if raw is None or raw == "":
        return default
    limit = int(raw)
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return limit


def commit(runtime: SqlAlchemyRuntime | None) -> None:
    """Commit when a SQL runtime is active."""
    if runtime is not None:
        runtime.commit()


def rollback(runtime: SqlAlchemyRuntime | None) -> None:
    """Rollback when a SQL runtime is active."""
    if runtime is not None:
        runtime.rollback()


def require_permission(
    permission: str,
) -> tuple[Response, int, dict[str, str]] | None:
    """Require one platform-level permission."""
    values = set(request.headers.get("X-Platform-Permissions", "").split())
    if permission in values:
        return None
    return problem(403, "PERMISSION_DENIED", "Permission denied")


def parse_if_match(value: str | None) -> int | None:
    """Parse a weak or strong integer ETag."""
    if not value:
        return None
    try:
        return int(value.strip('W/"'))
    except ValueError:
        return None


def template_data(item: WorkflowTemplateVersion) -> dict[str, object]:
    """Serialize a workflow template version."""
    return {
        "template_key": item.template_key,
        "version": item.version_no,
        "name": item.name,
        "definition": item.definition,
        "status": item.status,
    }


def instance_data(item: WorkflowInstance) -> dict[str, object]:
    """Serialize a workflow instance and transition history."""
    data = asdict(item)
    data["history"] = [asdict(entry) for entry in item.history]
    return data


def success(data: object) -> Response:
    """Create a successful API envelope."""
    return jsonify({"data": data, "meta": {"trace_id": g.trace_id}})


def problem(
    status: int,
    code: str,
    detail: str,
) -> tuple[Response, int, dict[str, str]]:
    """Create an RFC 9457-compatible problem response."""
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
