"""TD Flask component tests."""
from uuid import uuid4

from td_service.app import create_app
from td_service.repository import MemoryUnitOfWork


def headers(actor_id: object, key: str = "key-1") -> dict[str, str]:
    return {"X-Actor-Id": str(actor_id), "Idempotency-Key": key}


def payload() -> dict[str, object]:
    return {
        "business_no": "TD-100",
        "title": "Checkout fails",
        "description": "Payment cannot complete",
        "severity": "major",
        "priority": "p1",
        "defect_type": "functional",
        "expected_result": "Payment completes",
        "actual_result": "Gateway error",
        "reproduction_steps": ["Open checkout", "Pay"],
    }


def test_create_is_idempotent_and_project_scoped() -> None:
    uow = MemoryUnitOfWork()
    client = create_app(uow).test_client()
    actor_id = uuid4()
    project_id = uuid4()
    first = client.post(f"/api/v1/projects/{project_id}/defects", json=payload(), headers=headers(actor_id))
    replay = client.post(f"/api/v1/projects/{project_id}/defects", json=payload(), headers=headers(actor_id))
    assert first.status_code == replay.status_code == 201
    assert first.json == replay.json
    defect_id = first.json["data"]["id"]
    hidden = client.get(f"/api/v1/projects/{uuid4()}/defects/{defect_id}")
    assert hidden.status_code == 404
    assert len(uow.outbox) == 1


def test_transition_requires_matching_etag_and_emits_outbox() -> None:
    uow = MemoryUnitOfWork()
    client = create_app(uow).test_client()
    actor_id = uuid4()
    project_id = uuid4()
    created = client.post(f"/api/v1/projects/{project_id}/defects", json=payload(), headers=headers(actor_id))
    defect_id = created.json["data"]["id"]
    stale = client.post(
        f"/api/v1/projects/{project_id}/defects/{defect_id}/transitions",
        json={"action": "assign", "assignee_id": str(uuid4())},
        headers={**headers(actor_id, "transition-1"), "If-Match": '"99"'},
    )
    assert stale.status_code == 412
    success = client.post(
        f"/api/v1/projects/{project_id}/defects/{defect_id}/transitions",
        json={"action": "assign", "assignee_id": str(uuid4())},
        headers={**headers(actor_id, "transition-1"), "If-Match": '"1"'},
    )
    assert success.status_code == 200
    assert success.json["data"]["status"] == "assigned"
    assert success.headers["ETag"] == '"2"'
    assert [event["event_type"] for event in uow.outbox] == ["Defect.Created", "Defect.Assigned"]
