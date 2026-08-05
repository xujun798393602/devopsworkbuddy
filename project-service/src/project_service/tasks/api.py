"""Task and Worklog HTTP routes."""

from flask import Blueprint, current_app, g, jsonify, request

from project_service.shared.errors import ValidationError
from project_service.shared.http import (
    decode_cursor,
    parse_limit,
    require_idempotency_key,
    require_if_match,
)
from project_service.shared.idempotency import StoredResponse

tasks_blueprint = Blueprint("tasks", __name__, url_prefix="/api/v1/projects/<project_id>/tasks")


def _service():
    return current_app.extensions["task_service"]


def _payload() -> dict[str, object]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValidationError("Request body must be a JSON object")
    return value


def _response(data, status=200, etag=None, meta=None):
    response_meta = {"trace_id": g.request_context.trace_id}
    if meta:
        response_meta.update(meta)
    response = jsonify({"data": data, "meta": response_meta})
    response.status_code = status
    if etag is not None:
        response.headers["ETag"] = f'"{etag}"'
    return response


def _stored(value: StoredResponse):
    response = current_app.response_class(status=value.status) if value.body is None else jsonify(value.body)
    response.status_code = value.status
    response.headers.update(value.headers)
    if value.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response


@tasks_blueprint.get("")
def list_tasks(project_id):
    page = _service().list_tasks(project_id, g.request_context, parse_limit(request), decode_cursor(request.args.get("after"), project_id))
    return _response([item.to_dict() for item in page.items], meta={"next_cursor": page.next_cursor, "has_more": page.has_more})


@tasks_blueprint.post("")
def create_task(project_id):
    return _stored(_service().create_task(project_id, _payload(), g.request_context, require_idempotency_key(request)))


@tasks_blueprint.get("/<task_id>")
def get_task(project_id, task_id):
    item = _service().get_task(project_id, task_id, g.request_context)
    return _response(item.to_dict(), etag=item.version)


@tasks_blueprint.patch("/<task_id>")
def update_task(project_id, task_id):
    return _stored(_service().update_task(project_id, task_id, _payload(), require_if_match(request), g.request_context, require_idempotency_key(request)))


@tasks_blueprint.post("/<task_id>/transitions")
def transition_task(project_id, task_id):
    return _stored(_service().transition_task(project_id, task_id, _payload(), require_if_match(request), g.request_context, require_idempotency_key(request)))


@tasks_blueprint.get("/<task_id>/worklogs")
def list_worklogs(project_id, task_id):
    return _response([item.to_dict() for item in _service().list_worklogs(project_id, task_id, g.request_context)])


@tasks_blueprint.post("/<task_id>/worklogs")
def record_worklog(project_id, task_id):
    return _stored(_service().record_worklog(project_id, task_id, _payload(), g.request_context, require_idempotency_key(request)))


@tasks_blueprint.post("/<task_id>/worklogs/<worklog_id>/corrections")
def correct_worklog(project_id, task_id, worklog_id):
    return _stored(_service().correct_worklog(project_id, task_id, worklog_id, _payload(), g.request_context, require_idempotency_key(request)))
