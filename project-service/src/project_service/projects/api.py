from flask import Blueprint, current_app, g, jsonify, request

from project_service.shared.errors import ValidationError
from project_service.shared.http import require_idempotency_key
from project_service.shared.idempotency import StoredResponse

projects_blueprint = Blueprint("projects", __name__, url_prefix="/api/v1/projects")


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
