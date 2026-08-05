"""In-memory Flask API component integration; not PostgreSQL/RabbitMQ acceptance."""

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
for item in ["iam-service/src", "devops-api-gateway/src", "workflow-service/src", "audit-service/src", "notification-service/src"]:
    sys.path.insert(0, str(ROOT / item))


class FlaskPorts:
    """Translate BFF upstream calls into real Flask test-client requests."""

    def __init__(self, iam_client, workflow_client) -> None:
        self.iam = iam_client
        self.workflow = workflow_client

    def login(self, username: str) -> dict[str, object]:
        response = self.iam.post("/api/v1/auth/login", json={"username": username}, headers={"X-Trace-Id": "golden-login"})
        if response.status_code != 201:
            raise PermissionError
        return response.get_json()["data"]

    def refresh(self, refresh_token: str) -> dict[str, object]:
        response = self.iam.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        if response.status_code != 200:
            raise PermissionError
        return response.get_json()["data"]

    def logout(self, refresh_token: str) -> None:
        self.iam.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})

    def principal(self, access_token: str) -> dict[str, object]:
        response = self.iam.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {access_token}"}
        )
        if response.status_code != 200:
            raise PermissionError("Access token is invalid")
        return dict(response.get_json()["data"])

    def request(
        self,
        path: str,
        method: str,
        access_token: str,
        payload: object | None,
        headers: dict[str, str],
        query_string: str,
    ) -> tuple[int, object]:
        if path == "me":
            response = self.iam.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            return response.status_code, response.get_json()
        target = f"/api/{path.lstrip('/')}"
        if query_string:
            target = f"{target}?{query_string}"
        response = self.workflow.open(
            target,
            method=method,
            json=payload,
            headers=dict(headers),
        )
        return response.status_code, response.get_json(silent=True) or {}


def csrf_headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token, "Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"}


def test_flask_api_golden_chain() -> None:
    from audit_service.app import create_app as audit_app
    from gateway.app import GatewaySettings
    from gateway.app import create_app as gateway_app
    from iam_service.app import create_app as iam_app
    from iam_service.config import Settings
    from notification_service.app import create_app as notification_app
    from workflow_service.app import create_app as workflow_app
    from workflow_service.integrations.project_authorization import ControlledAuthorizer

    iam = iam_app(Settings()).test_client()
    grants = {("developer", "project-1", action) for action in ("workflow.start", "workflow.read", "workflow.transition")}
    workflow = workflow_app(authorizer=ControlledAuthorizer(grants)).test_client()
    audit = audit_app().test_client()
    notification = notification_app().test_client()
    bff = gateway_app(FlaskPorts(iam, workflow), GatewaySettings()).test_client()

    bff.get("/bff/session")
    csrf = bff.get_cookie("devops_csrf").value
    login = bff.post("/bff/auth/login", json={"username": "developer"}, headers=csrf_headers(csrf))
    assert login.status_code == 200 and login.headers.get("Set-Cookie")
    principal = login.get_json()["data"]["principal"]
    actor = principal["id"]

    denied = workflow.post("/api/v1/workflow-instances", json={"project_id": "other", "business_object_type": "task", "business_object_id": "task-1"}, headers={"X-Actor-Id": actor, "Idempotency-Key": "deny"})
    assert denied.status_code == 403 and denied.content_type == "application/problem+json"

    # The controlled authorizer uses explicit API-level grants for the IAM identity.
    workflow.application.extensions["workflow_service"].authorizer.grants.update({(actor, "project-1", action) for action in ("workflow.start", "workflow.read", "workflow.transition")})
    payload = {"project_id": "project-1", "business_object_type": "task", "business_object_id": "task-1"}
    started = workflow.post("/api/v1/workflow-instances", json=payload, headers={"X-Actor-Id": actor, "Idempotency-Key": "start"})
    replay = workflow.post("/api/v1/workflow-instances", json=payload, headers={"X-Actor-Id": actor, "Idempotency-Key": "start"})
    instance = started.get_json()["data"]
    assert started.status_code == 201 and replay.get_json()["data"]["id"] == instance["id"]
    moved = workflow.post(f"/api/v1/workflow-instances/{instance['id']}/transitions", json={"action": "start"}, headers={"X-Actor-Id": actor, "Idempotency-Key": "move", "If-Match": '"1"'})
    assert moved.status_code == 200 and moved.headers["X-Trace-Id"]

    audit_event = {"event_id": "evt-1", "occurred_at": datetime.now(UTC).isoformat(), "trace_id": moved.headers["X-Trace-Id"], "actor": {"id": actor, "type": "user"}, "project_id": "project-1", "resource": {"type": "workflow", "id": instance["id"]}, "action": "workflow.transitioned", "result": "success", "source": "workflow-service"}
    assert audit.post("/internal/api/v1/audit-records", json=audit_event, headers={"X-Service-Scopes": "audit:ingest"}).status_code == 201

    event = {"recipient_id": actor, "source_event_id": "evt-1", "template_key": "workflow.transitioned", "category": "workflow", "variables": {"instance_id": instance["id"], "to_state": "in_progress"}, "target_url": f"/app/workflows/{instance['id']}"}
    delivery = notification.post("/internal/api/v1/notifications", json=event, headers={"X-Service-Scopes": "notification:ingest"}).get_json()["data"]
    listed = notification.get("/api/v1/me/notifications", headers={"X-Actor-Id": actor})
    assert len(listed.get_json()["data"]) == 1
    assert notification.put(f"/api/v1/me/notifications/{delivery['id']}/read", headers={"X-Actor-Id": actor}).status_code == 200
    preference = notification.put("/api/v1/me/notification-preferences", json={"category": "workflow", "enabled": False, "version": 1}, headers={"X-Actor-Id": actor})
    assert preference.status_code == 200

    csrf = bff.get_cookie("devops_csrf").value
    assert bff.post("/bff/auth/logout", headers=csrf_headers(csrf)).status_code == 204
    protected = bff.get("/bff/api/v1/me")
    assert protected.status_code == 401 and protected.content_type == "application/problem+json"


def test_real_postgres_and_rabbitmq_explicitly_not_claimed() -> None:
    import pytest

    pytest.skip(
        "Requires isolated PostgreSQL/RabbitMQ; in-memory API integration is not "
        "infrastructure acceptance and no AMQP client exists for event E2E"
    )
