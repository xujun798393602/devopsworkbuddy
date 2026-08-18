"""Portal dashboard summary contract tests for tp-service."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from tp_service.app import (
    create_app,
    parse_portal_limit,
    parse_project_ids,
    portal_cross_project,
)
from tp_service.config import Config
from tp_service.domain import CaseRun
from tp_service.domain import TestCase as LibraryCase
from tp_service.domain import TestExecution as ExecutionAggregate
from tp_service.execution import ManagedExecution, ManagedPlan
from tp_service.repository import MemoryPortalRepository, MemoryUnitOfWork
from tp_service.service import TpPortalService, derive_execution_status

PROJECT_A = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_B = UUID("22222222-2222-2222-2222-222222222222")
ACTOR = UUID("33333333-3333-3333-3333-333333333333")
OTHER_ACTOR = UUID("44444444-4444-4444-4444-444444444444")
CROSS_PROJECT_PERMISSION = "portal:cross-project-view"


def _case(project_id: UUID, business_no: str) -> LibraryCase:
    """Build a minimal library case for counting purposes."""
    return LibraryCase(
        uuid4(),
        project_id,
        business_no,
        uuid4(),
        f"case {business_no}",
        ACTOR,
        "functional",
        "p1",
        "active",
        "manual",
        None,
        (),
        1,
    )


def _plan(project_id: UUID, business_no: str) -> ManagedPlan:
    """Build a minimal plan head for counting purposes."""
    return ManagedPlan(uuid4(), project_id, business_no, ACTOR, "ready", (), "hash", 1)


def _execution(
    project_id: UUID,
    plan: ManagedPlan,
    status: str,
    case_statuses: tuple[str, ...] = (),
    *,
    assignee_id: UUID = ACTOR,
    round_no: int = 1,
) -> ManagedExecution:
    """Build an execution whose latest attempts hold the requested statuses."""
    attempts: dict[UUID, list[CaseRun]] = {}
    for case_status in case_statuses:
        case_version_ref = uuid4()
        attempts[case_version_ref] = [CaseRun(uuid4(), case_version_ref, 1, case_status, "")]
    aggregate = ExecutionAggregate(
        uuid4(),
        project_id,
        plan.id,
        uuid4(),
        assignee_id,
        status,
        attempts,
        1,
    )
    return ManagedExecution(aggregate, round_no)


@pytest.fixture()
def uow() -> MemoryUnitOfWork:
    """Seed a deterministic two-project TP dataset."""
    store = MemoryUnitOfWork()
    for index in range(3):
        case = _case(PROJECT_A, f"TC-A-{index}")
        store.cases[(PROJECT_A, case.id)] = case
    case_b = _case(PROJECT_B, "TC-B-0")
    store.cases[(PROJECT_B, case_b.id)] = case_b

    plan_a = _plan(PROJECT_A, "TP-A-1")
    plan_b = _plan(PROJECT_B, "TP-B-1")
    store.plans[(PROJECT_A, plan_a.id)] = plan_a
    store.plans[(PROJECT_B, plan_b.id)] = plan_b

    executions = [
        # pending: never started.
        _execution(PROJECT_A, plan_a, "draft", assignee_id=OTHER_ACTOR, round_no=1),
        _execution(PROJECT_A, plan_a, "draft", assignee_id=ACTOR, round_no=2),
        # running: one terminal attempt and one still in flight.
        _execution(PROJECT_A, plan_a, "running", ("passed", "running"), round_no=3),
        # passed: every latest attempt is terminal and non-failing.
        _execution(PROJECT_A, plan_a, "running", ("passed", "skipped"), round_no=4),
        # failed: a blocked attempt poisons the whole execution.
        _execution(PROJECT_A, plan_a, "running", ("passed", "blocked"), round_no=5),
        # project B stays outside the default scope.
        _execution(PROJECT_B, plan_b, "running", ("failed",), round_no=1),
    ]
    for managed in executions:
        store.executions[(managed.aggregate.project_id, managed.aggregate.id)] = managed
    return store


@pytest.fixture()
def service(uow: MemoryUnitOfWork) -> TpPortalService:
    """Bind the portal service to the in-memory projection."""
    return TpPortalService(MemoryPortalRepository(uow))


def test_summary_buckets_partition_every_execution(service: TpPortalService) -> None:
    """The four buckets must sum to execution_total for the scoped projects."""
    data = service.summary([PROJECT_A], ACTOR)

    assert data["case_total"] == 3
    assert data["plan_total"] == 1
    assert data["execution_total"] == 5
    assert data["execution_by_status"] == {
        "pending": 2,
        "running": 1,
        "passed": 1,
        "failed": 1,
    }
    assert sum(data["execution_by_status"].values()) == data["execution_total"]


def test_pass_rate_is_two_decimals_and_null_without_attempts(
    service: TpPortalService,
    uow: MemoryUnitOfWork,
) -> None:
    """pass_rate uses passed/(passed+failed) and is null when the denominator is 0."""
    assert service.summary([PROJECT_A], ACTOR)["pass_rate"] == 0.5

    only_pending = MemoryUnitOfWork()
    plan = _plan(PROJECT_A, "TP-A-9")
    only_pending.plans[(PROJECT_A, plan.id)] = plan
    managed = _execution(PROJECT_A, plan, "draft")
    only_pending.executions[(PROJECT_A, managed.aggregate.id)] = managed

    data = TpPortalService(MemoryPortalRepository(only_pending)).summary([PROJECT_A], ACTOR)
    assert data["pass_rate"] is None
    assert data["execution_by_status"] == {"pending": 1, "running": 0, "passed": 0, "failed": 0}


def test_pending_executions_shape_and_actor_priority(service: TpPortalService) -> None:
    """Pending items follow the frozen contract and surface the caller first."""
    data = service.summary([PROJECT_A], ACTOR)
    pending = data["pending_executions"]

    assert pending["count"] == 2
    assert len(pending["items"]) == 2
    first = pending["items"][0]
    assert set(first) == {"id", "project_id", "plan_id", "name", "status", "planned_at"}
    assert first["status"] == "pending"
    assert first["planned_at"] is None
    assert first["name"] == "TP-A-1 R2"
    assert first["project_id"] == str(PROJECT_A)


def test_execution_limit_truncates_items_but_not_count(service: TpPortalService) -> None:
    """The count reports the whole scope while items honour the limit."""
    data = service.summary([PROJECT_A], ACTOR, execution_limit=1)

    assert data["pending_executions"]["count"] == 2
    assert len(data["pending_executions"]["items"]) == 1


def test_unknown_scope_returns_structured_zeroes(service: TpPortalService) -> None:
    """An out-of-scope project never leaks other projects' statistics."""
    data = service.summary([uuid4()], ACTOR)

    assert data["case_total"] == 0
    assert data["plan_total"] == 0
    assert data["execution_total"] == 0
    assert data["execution_by_status"] == {"pending": 0, "running": 0, "passed": 0, "failed": 0}
    assert data["pass_rate"] is None
    assert data["pending_executions"] == {"count": 0, "items": []}


def test_empty_scope_without_cross_project_returns_zeroes(service: TpPortalService) -> None:
    """An empty project list must not be interpreted as a platform-wide scope."""
    data = service.summary([], ACTOR)

    assert data["case_total"] == 0
    assert data["execution_total"] == 0


def test_cross_project_scope_covers_every_project(service: TpPortalService) -> None:
    """Cross-project reads ignore project_ids and span the whole platform."""
    data = service.summary([], ACTOR, cross_project=True)

    assert data["case_total"] == 4
    assert data["plan_total"] == 2
    assert data["execution_total"] == 6
    assert data["execution_by_status"]["failed"] == 2


def test_derive_execution_status_handles_started_without_attempts() -> None:
    """A started execution with no recorded attempt is still running."""
    plan = _plan(PROJECT_A, "TP-A-8")
    snapshot = MemoryPortalRepository(MemoryUnitOfWork()).executions([], cross_project=True)
    assert snapshot == []

    store = MemoryUnitOfWork()
    store.plans[(PROJECT_A, plan.id)] = plan
    managed = _execution(PROJECT_A, plan, "running", ())
    store.executions[(PROJECT_A, managed.aggregate.id)] = managed
    [projected] = MemoryPortalRepository(store).executions([PROJECT_A])

    assert derive_execution_status(projected) == "running"


def test_latest_attempt_wins_over_earlier_reruns() -> None:
    """Only the latest attempt of each case version drives the derived status."""
    store = MemoryUnitOfWork()
    plan = _plan(PROJECT_A, "TP-A-7")
    store.plans[(PROJECT_A, plan.id)] = plan
    case_version_ref = uuid4()
    aggregate = ExecutionAggregate(
        uuid4(),
        PROJECT_A,
        plan.id,
        uuid4(),
        ACTOR,
        "running",
        {
            case_version_ref: [
                CaseRun(uuid4(), case_version_ref, 1, "failed", "boom"),
                CaseRun(uuid4(), case_version_ref, 2, "passed", ""),
            ]
        },
        1,
    )
    store.executions[(PROJECT_A, aggregate.id)] = ManagedExecution(aggregate, 1)

    [projected] = MemoryPortalRepository(store).executions([PROJECT_A])
    assert projected.latest_attempt_counts == {"passed": 1}
    assert derive_execution_status(projected) == "passed"


def test_parse_project_ids_drops_malformed_and_duplicate_entries() -> None:
    """CSV parsing is defensive and order preserving."""
    raw = f"{PROJECT_A},not-a-uuid,,{PROJECT_B},{PROJECT_A}"
    assert parse_project_ids(raw) == (PROJECT_A, PROJECT_B)
    assert parse_project_ids(None) == ()


def test_parse_portal_limit_bounds() -> None:
    """Limits fall back to the default and reject out-of-range values."""
    assert parse_portal_limit(None, 5, 50) == 5
    assert parse_portal_limit("", 5, 50) == 5
    assert parse_portal_limit("7", 5, 50) == 7
    with pytest.raises(ValueError):
        parse_portal_limit("0", 5, 50)
    with pytest.raises(ValueError):
        parse_portal_limit("51", 5, 50)


def test_portal_cross_project_requires_the_platform_permission() -> None:
    """Defence in depth: the header alone must never widen the scope."""
    assert portal_cross_project({"X-Portal-Cross-Project": "true"}) is False
    assert (
        portal_cross_project(
            {
                "X-Portal-Cross-Project": "true",
                "X-Platform-Permissions": f"project:read,{CROSS_PROJECT_PERMISSION}",
            }
        )
        is True
    )
    assert (
        portal_cross_project(
            {
                "X-Portal-Cross-Project": "false",
                "X-Platform-Permissions": CROSS_PROJECT_PERMISSION,
            }
        )
        is False
    )


def test_http_endpoint_scopes_by_project_ids(uow: MemoryUnitOfWork) -> None:
    """The HTTP adapter honours project_ids and returns the envelope shape."""
    client = create_app(uow, config=Config()).test_client()

    response = client.get(
        f"/api/v1/portal/tp-summary?project_ids={PROJECT_A}",
        headers={"X-Actor-Id": str(ACTOR), "X-Trace-Id": "trace-1"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["meta"]["trace_id"] == "trace-1"
    assert body["data"]["execution_total"] == 5
    assert body["data"]["case_total"] == 3


def test_http_endpoint_ignores_cross_project_without_permission(uow: MemoryUnitOfWork) -> None:
    """A forged cross-project header is ignored when the permission is absent."""
    client = create_app(uow, config=Config()).test_client()

    response = client.get(
        f"/api/v1/portal/tp-summary?project_ids={PROJECT_A}",
        headers={
            "X-Actor-Id": str(ACTOR),
            "X-Portal-Cross-Project": "true",
            "X-Platform-Permissions": "project:read",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["execution_total"] == 5


def test_http_endpoint_accepts_cross_project_with_permission(uow: MemoryUnitOfWork) -> None:
    """A permitted cross-project read spans every project."""
    client = create_app(uow, config=Config()).test_client()

    response = client.get(
        "/api/v1/portal/tp-summary",
        headers={
            "X-Actor-Id": str(ACTOR),
            "X-Portal-Cross-Project": "true",
            "X-Platform-Permissions": CROSS_PROJECT_PERMISSION,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["execution_total"] == 6


def test_http_endpoint_rejects_out_of_range_limit(uow: MemoryUnitOfWork) -> None:
    """An invalid execution_limit yields a problem+json validation error."""
    client = create_app(uow, config=Config()).test_client()

    response = client.get(
        f"/api/v1/portal/tp-summary?project_ids={PROJECT_A}&execution_limit=0",
        headers={"X-Actor-Id": str(ACTOR)},
    )

    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "VALIDATION_ERROR"
