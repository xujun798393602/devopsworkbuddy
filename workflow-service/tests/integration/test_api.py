from workflow_service.app import create_app
from workflow_service.integrations.project_authorization import ControlledAuthorizer


def test_workflow_api_authorization_idempotency_and_version() -> None:
    grants = {("user-1", "project-1", action) for action in ("workflow.start", "workflow.read", "workflow.transition")}
    client = create_app(authorizer=ControlledAuthorizer(grants)).test_client()
    payload = {"project_id": "project-1", "business_object_type": "task", "business_object_id": "task-1"}
    denied = client.post("/api/v1/workflow-instances", json=payload, headers={"X-Actor-Id": "other", "Idempotency-Key": "one"})
    assert denied.status_code == 403
    first = client.post("/api/v1/workflow-instances", json=payload, headers={"X-Actor-Id": "user-1", "Idempotency-Key": "one"})
    assert first.status_code == 201
    instance = first.get_json()["data"]
    replay = client.post("/api/v1/workflow-instances", json=payload, headers={"X-Actor-Id": "user-1", "Idempotency-Key": "one"})
    assert replay.get_json()["data"]["id"] == instance["id"]
    invalid = client.post(f"/api/v1/workflow-instances/{instance['id']}/transitions", json={"action": "close"}, headers={"X-Actor-Id": "user-1", "Idempotency-Key": "two", "If-Match": '"1"'})
    assert invalid.status_code == 409
    moved = client.post(f"/api/v1/workflow-instances/{instance['id']}/transitions", json={"action": "start"}, headers={"X-Actor-Id": "user-1", "Idempotency-Key": "three", "If-Match": '"1"'})
    assert moved.status_code == 200
    stale = client.post(f"/api/v1/workflow-instances/{instance['id']}/transitions", json={"action": "complete"}, headers={"X-Actor-Id": "user-1", "Idempotency-Key": "four", "If-Match": '"1"'})
    assert stale.status_code == 412
