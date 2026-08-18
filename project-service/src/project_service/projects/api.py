from flask import Blueprint, current_app, g, jsonify, request

from project_service.projects.service import PORTAL_PROJECT_LIMIT_DEFAULT, PORTAL_PROJECT_LIMIT_MAX
from project_service.shared.errors import ValidationError
from project_service.shared.http import (
    parse_portal_limit,
    portal_cross_project,
    require_idempotency_key,
)
from project_service.shared.idempotency import StoredResponse

projects_blueprint = Blueprint("projects", __name__, url_prefix="/api/v1/projects")
# Portal aggregation endpoints live under a prefix the gateway proxy cannot reach,
# so only the portal aggregator (which calls upstreams directly) can consume them.
portal_blueprint = Blueprint("projects_portal", __name__, url_prefix="/api/v1/portal")


def _service():
    return current_app.extensions["project_service"]


def _payload() -> dict[str, object]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValidationError("Request body must be a JSON object")
    return value


def _stored(value: StoredResponse):
    response = current_app.response_class(status=value.status) if value.body is None else jsonify(value.body)
    response.status_code = value.status
    response.headers.update(value.headers)
    if value.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response


@projects_blueprint.post("")
def create_project():
    return _stored(
        _service().create_project(_payload(), g.request_context, require_idempotency_key(request))
    )


@projects_blueprint.get("")
def list_projects():
    return jsonify(
        {
            "data": [x.to_dict() for x in _service().list_projects(g.request_context.actor_id)],
            "meta": {"trace_id": g.request_context.trace_id},
        }
    )


@projects_blueprint.get("/<project_id>")
def get_project(project_id):
    item = _service().get_project(project_id, g.request_context.actor_id)
    response = jsonify({"data": item.to_dict(), "meta": {"trace_id": g.request_context.trace_id}})
    response.headers["ETag"] = f'"{item.version}"'
    return response


@portal_blueprint.get("/projects-overview")
def portal_projects_overview():
    """Return the batched project block plus the project ids for downstream fan-out."""
    limit = parse_portal_limit(
        request, "limit", PORTAL_PROJECT_LIMIT_DEFAULT, PORTAL_PROJECT_LIMIT_MAX
    )
    data = _service().portal_overview(
        g.request_context.actor_id,
        cross_project=portal_cross_project(request),
        limit=limit,
    )
    return jsonify({"data": data, "meta": {"trace_id": g.request_context.trace_id}})
