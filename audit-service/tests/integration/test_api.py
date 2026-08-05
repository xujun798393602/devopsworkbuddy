from datetime import UTC, datetime, timedelta

from audit_service.app import create_app
from audit_service.records.repository import InMemoryAuditRepository


def event(number: int) -> dict[str, object]:
    return {"event_id": f"evt-{number}", "occurred_at": (datetime.now(UTC) + timedelta(seconds=number)).isoformat(), "trace_id": "trace", "actor": {"id": "user-1", "type": "user"}, "project_id": "project-1", "resource": {"type": "workflow", "id": str(number)}, "action": "changed", "result": "success", "source": "test"}


def test_ingest_security_dedup_and_stable_pagination() -> None:
    client = create_app(InMemoryAuditRepository()).test_client()
    assert client.post("/internal/api/v1/audit-records", json=event(1)).status_code == 403
    headers = {"X-Service-Scopes": "audit:ingest"}
    first = client.post("/internal/api/v1/audit-records", json=event(1), headers=headers)
    duplicate = client.post("/internal/api/v1/audit-records", json=event(1), headers=headers)
    client.post("/internal/api/v1/audit-records", json=event(2), headers=headers)
    assert first.get_json()["data"]["id"] == duplicate.get_json()["data"]["id"]
    assert client.get("/api/v1/audit-records").status_code == 403
    now = datetime.now(UTC)
    query = {"from": (now - timedelta(days=1)).isoformat(), "to": (now + timedelta(days=1)).isoformat(), "limit": 1}
    page = client.get("/api/v1/audit-records", query_string=query, headers={"X-Platform-Permissions": "audit.read"})
    assert page.status_code == 200 and len(page.get_json()["data"]) == 1
    assert page.get_json()["meta"]["next_cursor"]


def test_sensitive_fields_are_rejected() -> None:
    payload = event(3)
    payload["metadata"] = {"access_token": "secret"}
    assert create_app(InMemoryAuditRepository()).test_client().post("/internal/api/v1/audit-records", json=payload, headers={"X-Service-Scopes": "audit:ingest"}).status_code == 422
