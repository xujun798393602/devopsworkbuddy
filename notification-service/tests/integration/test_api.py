from notification_service.app import create_app
from notification_service.notifications.service import NotificationService


def payload(recipient: str = "user-1") -> dict[str, object]:
    return {"recipient_id": recipient, "source_event_id": "event-1", "template_key": "workflow.started", "category": "workflow", "variables": {"instance_id": "<unsafe>"}, "target_url": "/app/workflows/one"}


def test_ingest_dedup_recipient_isolation_and_read_all() -> None:
    client = create_app(NotificationService()).test_client()
    assert client.post("/internal/api/v1/notifications", json=payload()).status_code == 403
    headers = {"X-Service-Scopes": "notification:ingest"}
    first = client.post("/internal/api/v1/notifications", json=payload(), headers=headers)
    second = client.post("/internal/api/v1/notifications", json=payload(), headers=headers)
    delivery_id = first.get_json()["data"]["id"]
    assert second.get_json()["data"]["id"] == delivery_id
    assert client.get(f"/api/v1/me/notifications/{delivery_id}", headers={"X-Actor-Id": "other"}).status_code == 404
    detail = client.get(f"/api/v1/me/notifications/{delivery_id}", headers={"X-Actor-Id": "user-1"})
    assert "<unsafe>" not in detail.get_json()["data"]["notification"]["body"]
    client.put("/api/v1/me/notifications/read-all", headers={"X-Actor-Id": "user-1"})
    assert client.get("/api/v1/me/notifications/unread-count", headers={"X-Actor-Id": "user-1"}).get_json()["data"]["count"] == 0


def test_security_preference_cannot_be_disabled() -> None:
    client = create_app(NotificationService()).test_client()
    response = client.put("/api/v1/me/notification-preferences", json={"category": "security", "enabled": False, "version": 1}, headers={"X-Actor-Id": "user-1"})
    assert response.status_code == 422
