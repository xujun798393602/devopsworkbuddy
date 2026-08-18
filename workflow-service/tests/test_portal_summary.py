"""Portal pending-approvals read projection tests (in-memory + SQLAlchemy)."""
from datetime import UTC, datetime
from uuid import uuid4

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from workflow_service.app import create_app
from workflow_service.integrations.project_authorization import ControlledAuthorizer
from workflow_service.persistence import (
    Base,
    SqlAlchemyPortalRepository,
    SqlAlchemyWorkflowRepository,
)
from workflow_service.workflows.models import WorkflowInstance, WorkflowTransition
from workflow_service.workflows.repository import InMemoryWorkflowRepository

PROJECT_A = "project-a"
PROJECT_B = "project-b"
ACTOR = "approver-1"
CROSS_HEADERS = {
    "X-Portal-Cross-Project": "true",
    "X-Platform-Permissions": "portal:cross-project-view",
}


def _instance(
    instance_id: str,
    project_id: str,
    state: str,
    history: list[WorkflowTransition] | None = None,
    started_by: str = ACTOR,
) -> WorkflowInstance:
    return WorkflowInstance(
        instance_id,
        project_id,
        "task",
        f"obj-{instance_id}",
        "system.task-lifecycle",
        1,
        state,
        started_by,
        history=history or [],
    )


def _client_with(instances: list[WorkflowInstance]) -> Flask:
    repo = InMemoryWorkflowRepository()
    for inst in instances:
        repo.instances[inst.id] = inst
    return create_app(repo=repo, authorizer=ControlledAuthorizer(set())).test_client()


def test_pending_approvals_excludes_non_pending_states() -> None:
    instances = [
        _instance("i1", PROJECT_A, "todo"),
        _instance("i2", PROJECT_A, "in_progress"),
        _instance("i3", PROJECT_A, "done"),
        _instance("i4", PROJECT_A, "closed"),
        _instance("i5", PROJECT_A, "canceled"),
    ]
    client = _client_with(instances)
    resp = client.get(f"/api/v1/portal/pending-approvals?project_ids={PROJECT_A}")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["count"] == 1
    assert [item["id"] for item in data["items"]] == ["i1"]


def test_pending_approvals_scoped_to_project_ids() -> None:
    instances = [
        _instance("i1", PROJECT_A, "todo"),
        _instance("i2", PROJECT_B, "todo"),
    ]
    client = _client_with(instances)
    resp = client.get(f"/api/v1/portal/pending-approvals?project_ids={PROJECT_A}")
    data = resp.get_json()["data"]
    assert data["count"] == 1
    assert data["items"][0]["project_id"] == PROJECT_A


def test_empty_scope_without_cross_project_is_zero() -> None:
    client = _client_with([_instance("i1", PROJECT_A, "todo")])
    resp = client.get("/api/v1/portal/pending-approvals")
    assert resp.get_json()["data"] == {"count": 0, "items": []}


def test_cross_project_with_permission_covers_all() -> None:
    instances = [
        _instance("i1", PROJECT_A, "todo"),
        _instance("i2", PROJECT_B, "todo"),
        _instance("i3", PROJECT_A, "in_progress"),
    ]
    client = _client_with(instances)
    resp = client.get("/api/v1/portal/pending-approvals", headers=CROSS_HEADERS)
    data = resp.get_json()["data"]
    assert data["count"] == 2
    assert {item["id"] for item in data["items"]} == {"i1", "i2"}


def test_cross_project_without_permission_ignored() -> None:
    instances = [
        _instance("i1", PROJECT_A, "todo"),
        _instance("i2", PROJECT_B, "todo"),
    ]
    client = _client_with(instances)
    resp = client.get(
        "/api/v1/portal/pending-approvals",
        headers={"X-Portal-Cross-Project": "true"},
    )
    assert resp.get_json()["data"] == {"count": 0, "items": []}


def test_limit_truncates_items_not_count() -> None:
    instances = [_instance(f"i{n}", PROJECT_A, "todo") for n in range(7)]
    client = _client_with(instances)
    resp = client.get(
        f"/api/v1/portal/pending-approvals?project_ids={PROJECT_A}&limit=3"
    )
    data = resp.get_json()["data"]
    assert data["count"] == 7
    assert len(data["items"]) == 3


def test_unknown_scope_returns_zero() -> None:
    client = _client_with([_instance("i1", PROJECT_A, "todo")])
    resp = client.get("/api/v1/portal/pending-approvals?project_ids=nope")
    assert resp.get_json()["data"] == {"count": 0, "items": []}


def test_limit_out_of_range_returns_422() -> None:
    client = _client_with([_instance("i1", PROJECT_A, "todo")])
    below = client.get(
        f"/api/v1/portal/pending-approvals?project_ids={PROJECT_A}&limit=0"
    )
    assert below.status_code == 422
    assert below.get_json()["error_code"] == "INVALID_LIMIT"
    above = client.get(
        f"/api/v1/portal/pending-approvals?project_ids={PROJECT_A}&limit=99"
    )
    assert above.status_code == 422


def test_started_at_derived_from_history_or_none() -> None:
    t0 = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)
    with_history = _instance(
        "i1",
        PROJECT_A,
        "todo",
        history=[
            WorkflowTransition(str(uuid4()), "todo", "todo", "reopen", ACTOR, None, t0)
        ],
    )
    no_history = _instance("i2", PROJECT_A, "todo")
    client = _client_with([with_history, no_history])
    resp = client.get(f"/api/v1/portal/pending-approvals?project_ids={PROJECT_A}")
    by_id = {item["id"]: item for item in resp.get_json()["data"]["items"]}
    assert by_id["i1"]["started_at"] == t0.isoformat()
    assert by_id["i2"]["started_at"] is None


def test_sql_portal_repository_scope_and_no_leak() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        repo = SqlAlchemyWorkflowRepository(session)
        repo.save_instance(_instance("i1", PROJECT_A, "todo"))
        repo.save_instance(_instance("i2", PROJECT_B, "in_progress"))
        session.commit()
    with Session(engine) as session:
        portal = SqlAlchemyPortalRepository(session)
        scoped = portal.pending_approvals((PROJECT_A,), cross_project=False)
        assert [snapshot.project_id for snapshot in scoped] == [PROJECT_A]
        assert portal.pending_approvals((), cross_project=False) == []
        all_pending = portal.pending_approvals((), cross_project=True)
        assert len(all_pending) == 1


def test_sql_portal_started_at_from_earliest_transition() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    t0 = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)
    with Session(engine, expire_on_commit=False) as session:
        repo = SqlAlchemyWorkflowRepository(session)
        repo.save_instance(
            _instance(
                "i1",
                PROJECT_A,
                "todo",
                history=[
                    WorkflowTransition(str(uuid4()), "todo", "todo", "reopen", ACTOR, None, t0),
                    WorkflowTransition(str(uuid4()), "todo", "todo", "reopen", ACTOR, None, t1),
                ],
            )
        )
        session.commit()
    with Session(engine) as session:
        portal = SqlAlchemyPortalRepository(session)
        snapshots = portal.pending_approvals((PROJECT_A,), cross_project=False)
        assert "2026-08-10T02:00:00" in snapshots[0].started_at
