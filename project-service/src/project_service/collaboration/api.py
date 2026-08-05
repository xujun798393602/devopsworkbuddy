"""Collaboration HTTP routes."""

from flask import Blueprint, current_app, g, jsonify, request

from project_service.shared.errors import ValidationError
from project_service.shared.http import require_idempotency_key, require_if_match
from project_service.shared.idempotency import StoredResponse

collaboration_blueprint = Blueprint("collaboration", __name__, url_prefix="/api/v1/projects/<project_id>")


def _service():
    return current_app.extensions["collaboration_service"]


def _payload() -> dict[str, object]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValidationError("Request body must be a JSON object")
    return value


def _response(data, status=200, etag=None):
    response = jsonify({"data": data, "meta": {"trace_id": g.request_context.trace_id}})
    response.status_code = status
    if etag is not None:
        response.headers["ETag"] = f'"{etag}"'
    return response


def _stored(value: StoredResponse):
    if value.body is None:
        response = current_app.response_class(status=value.status)
    else:
        response = jsonify(value.body)
        response.status_code = value.status
    response.headers.update(value.headers)
    if value.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response


@collaboration_blueprint.get("/members")
def list_members(project_id):
    return _response([x.to_dict() for x in _service().list_members(project_id, g.request_context)])


@collaboration_blueprint.post("/members")
def add_member(project_id):
    return _stored(_service().add_member(project_id, _payload(), g.request_context, require_idempotency_key(request)))


@collaboration_blueprint.patch("/members/<membership_id>")
def change_member(project_id, membership_id):
    payload = _payload()
    return _stored(_service().change_member_role(project_id, membership_id, str(payload.get("role", "")), require_if_match(request), g.request_context, require_idempotency_key(request)))


@collaboration_blueprint.delete("/members/<membership_id>")
def remove_member(project_id, membership_id):
    return _stored(_service().remove_member(project_id, membership_id, require_if_match(request), g.request_context, require_idempotency_key(request)))


@collaboration_blueprint.post("/owner-transfers")
def transfer_owner(project_id):
    return _stored(_service().transfer_owner(project_id, _payload(), g.request_context, require_idempotency_key(request)))


@collaboration_blueprint.get("/versions")
def list_versions(project_id):
    return _response([x.to_dict() for x in _service().list_versions(project_id, g.request_context)])


@collaboration_blueprint.post("/versions")
def create_version(project_id):
    return _stored(_service().create_version(project_id, _payload(), g.request_context, require_idempotency_key(request)))


@collaboration_blueprint.get("/versions/<resource_id>")
def get_version(project_id, resource_id):
    item = _service().get_version(project_id, resource_id, g.request_context)
    return _response(item.to_dict(), etag=item.version)


@collaboration_blueprint.patch("/versions/<resource_id>")
def update_version(project_id, resource_id):
    return _stored(_service().update_version(project_id, resource_id, _payload(), require_if_match(request), g.request_context, require_idempotency_key(request)))


@collaboration_blueprint.post("/versions/<resource_id>/transitions")
def transition_version(project_id, resource_id):
    return _stored(_service().transition_version(project_id, resource_id, _payload(), g.request_context, require_idempotency_key(request), require_if_match(request)))


@collaboration_blueprint.get("/iterations")
def list_iterations(project_id):
    return _response([x.to_dict() for x in _service().list_iterations(project_id, g.request_context)])


@collaboration_blueprint.post("/iterations")
def create_iteration(project_id):
    return _stored(_service().create_iteration(project_id, _payload(), g.request_context, require_idempotency_key(request)))


@collaboration_blueprint.get("/iterations/<resource_id>")
def get_iteration(project_id, resource_id):
    item = _service().get_iteration(project_id, resource_id, g.request_context)
    return _response(item.to_dict(), etag=item.version)


@collaboration_blueprint.patch("/iterations/<resource_id>")
def update_iteration(project_id, resource_id):
    return _stored(_service().update_iteration(project_id, resource_id, _payload(), require_if_match(request), g.request_context, require_idempotency_key(request)))


@collaboration_blueprint.post("/iterations/<resource_id>/transitions")
def transition_iteration(project_id, resource_id):
    return _stored(_service().transition_iteration(project_id, resource_id, _payload(), g.request_context, require_idempotency_key(request), require_if_match(request)))
