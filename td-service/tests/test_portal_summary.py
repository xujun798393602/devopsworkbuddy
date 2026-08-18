"""Portal dashboard summary contract tests for td-service."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from td_service.app import (
    create_app,
    parse_portal_limit,
    parse_project_ids,
    portal_cross_project,
)
from td_service.config import Config
from td_service.domain import Defect, DefectStatus, SlaSnapshot
from td_service.repository import MemoryPortalRepository, MemoryUnitOfWork
from td_service.service import (
    TdPortalService,
    portal_severity,
    portal_sla_breached,
    portal_status,
)

PROJECT_A = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_B = UUID("22222222-2222-2222-2222-222222222222")
ACTOR = UUID("33333333-3333-3333-3333-333333333333")
OTHER_ACTOR = UUID("44444444-4444-4444-4444-444444444444")
CROSS_PROJECT_PERMISSION = "portal:cross-project-view"
NOW = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)


def _sla(*, breached: bool = False) -> SlaSnapshot:
    """Build an SLA snapshot whose due dates are stable relative to NOW."""
    offset = timedelta(hours=-1) if breached else timedelta(hours=48)
    return SlaSnapshot(
        policy_key="default-major",
        policy_version="v1",
        response_due_at=NOW + offset,
        resolution_due_at=NOW + offset,
    )


def _defect(
    project_id: UUID,
    business_no: str,
    *,
    status: DefectStatus = DefectStatus.NEW,
    severity: str = "major",
    priority: str = "p2",
    assignee_id: UUID | None = None,
    breached: bool = False,
) -> Defect:
    """Build a defect aggregate bypassing the workflow so states stay explicit."""
    defect = Defect(
        id=uuid4(),
        project_id=project_id,
        business_no=business_no,
        title=f"defect {business_no}",
        description="",
        severity=severity,
        priority=priority,
        defect_type="functional",
        reporter_id=OTHER_ACTOR,
        expected_result="expected",
        actual_result="actual",
        reproduction_steps=("step 1",),
        sla=_sla(breached=breached),
    )
    defect.status = status
    defect.assignee_id = assignee_id
    return defect


@pytest.fixture()
def uow() -> MemoryUnitOfWork:
    """Seed a deterministic two-project defect dataset."""
    store = MemoryUnitOfWork()
    defects = [
        _defect(PROJECT_A, "TD-A-01", status=DefectStatus.NEW, severity="blocker"),
        _defect(
            PROJECT_A,
            "TD-A-02",
            status=DefectStatus.ASSIGNED,
            severity="critical",
            assignee_id=ACTOR,
        ),
        _defect(
            PROJECT_A,
            "TD-A-03",
            status=DefectStatus.REOPENED,
            severity="major",
            assignee_id=ACTOR,
            breached=True,
        ),
        _defect(
            PROJECT_A,
            "TD-A-04",
            status=DefectStatus.IN_PROGRESS,
            severity="major",
            assignee_id=ACTOR,
        ),
        _defect(PROJECT_A, "TD-A-05", status=DefectStatus.FIXED, severity="minor"),
        _defect(
            PROJECT_A,
            "TD-A-06",
            status=DefectStatus.PENDING_VERIFICATION,
            severity="minor",
        ),
        _defect(
            PROJECT_A,
            "TD-A-07",
            status=DefectStatus.CLOSED,
            severity="trivial",
            assignee_id=ACTOR,
        ),
        _defect(PROJECT_A, "TD-A-08", status=DefectStatus.REJECTED, severity="trivial"),
        _defect(
            PROJECT_A,
            "TD-A-09",
            status=DefectStatus.DUPLICATE,
            severity="minor",
            assignee_id=ACTOR,
        ),
        _defect(
            PROJECT_B,
            "TD-B-01",
            status=DefectStatus.NEW,
            severity="critical",
            assignee_id=ACTOR,
        ),
    ]
    for defect in defects:
        store.defects[(defect.project_id, defect.id)] = defect
    return store


@pytest.fixture()
def service(uow: MemoryUnitOfWork) -> TdPortalService:
    """Bind the portal service to the in-memory projection."""
    return TdPortalService(MemoryPortalRepository(uow))


def test_status_and_severity_folding_matches_the_frozen_contract(
    service: TdPortalService,
) -> None:
    """Nine workflow states and five severities fold into four buckets each."""
    data = service.summary([PROJECT_A], ACTOR, now=NOW)

    assert data["total"] == 9
    assert data["by_status"] == {
        "new": 3,  # new + assigned + reopened
        "in_progress": 1,
        "resolved": 2,  # fixed + pending_verification
        "closed": 3,  # closed + rejected + duplicate
    }
    assert sum(data["by_status"].values()) == data["total"]
    assert data["by_severity"] == {
        "critical": 2,  # blocker + critical
        "high": 2,  # major
        "medium": 3,  # minor
        "low": 2,  # trivial
    }
    assert sum(data["by_severity"].values()) == data["total"]


def test_my_open_defects_filters_by_actor_and_excludes_closed(
    service: TdPortalService,
) -> None:
    """Only open defects assigned to the caller are reported as my work."""
    data = service.summary([PROJECT_A], ACTOR, now=NOW)
    mine = data["my_open_defects"]

    assert mine["count"] == 3
    business_numbers = [item["business_no"] for item in mine["items"]]
    assert business_numbers == ["TD-A-02", "TD-A-03", "TD-A-04"]
    first = mine["items"][0]
    assert set(first) == {
        "id",
        "project_id",
        "business_no",
        "title",
        "severity",
        "priority",
        "status",
        "sla_breached",
    }
    assert first["severity"] == "critical"
    assert first["status"] == "new"
    assert first["sla_breached"] is False


def test_my_open_defects_is_empty_without_an_actor(service: TdPortalService) -> None:
    """A missing actor identity must never leak everybody's defects."""
    data = service.summary([PROJECT_A], None, now=NOW)

    assert data["my_open_defects"] == {"count": 0, "items": []}
    assert data["total"] == 9


def test_defect_limit_truncates_items_but_not_count(service: TdPortalService) -> None:
    """The count reports the whole scope while items honour the limit."""
    data = service.summary([PROJECT_A], ACTOR, defect_limit=2, now=NOW)

    assert data["my_open_defects"]["count"] == 3
    assert len(data["my_open_defects"]["items"]) == 2


def test_sla_breach_is_evaluated_read_only(uow: MemoryUnitOfWork) -> None:
    """Elapsed due dates count as breached without mutating stored snapshots."""
    service = TdPortalService(MemoryPortalRepository(uow))
    data = service.summary([PROJECT_A], ACTOR, now=NOW)

    assert data["sla_breached"] == 1
    breached = next(
        item
        for item in data["my_open_defects"]["items"]
        if item["business_no"] == "TD-A-03"
    )
    assert breached["sla_breached"] is True
    stored = next(
        defect for defect in uow.defects.values() if defect.business_no == "TD-A-03"
    )
    assert stored.sla is not None
    assert stored.sla.response_breached is False
    assert stored.sla.resolution_breached is False


def test_closed_defects_keep_their_recorded_sla_verdict() -> None:
    """A terminal defect is never newly penalised by elapsed due dates."""
    store = MemoryUnitOfWork()
    defect = _defect(PROJECT_A, "TD-A-99", status=DefectStatus.CLOSED, breached=True)
    store.defects[(PROJECT_A, defect.id)] = defect

    data = TdPortalService(MemoryPortalRepository(store)).summary(
        [PROJECT_A], ACTOR, now=NOW
    )
    assert data["sla_breached"] == 0


def test_unknown_and_empty_scope_return_structured_zeroes(
    service: TdPortalService,
) -> None:
    """Out-of-scope or empty requests never leak other projects' statistics."""
    for scope in ([uuid4()], []):
        data = service.summary(scope, ACTOR, now=NOW)
        assert data["total"] == 0
        assert data["by_status"] == {
            "new": 0,
            "in_progress": 0,
            "resolved": 0,
            "closed": 0,
        }
        assert data["by_severity"] == {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }
        assert data["sla_breached"] == 0
        assert data["my_open_defects"] == {"count": 0, "items": []}


def test_cross_project_scope_covers_every_project(service: TdPortalService) -> None:
    """Cross-project reads ignore project_ids and span the whole platform."""
    data = service.summary([], ACTOR, cross_project=True, now=NOW)

    assert data["total"] == 10
    assert data["my_open_defects"]["count"] == 4


def test_status_and_severity_mappers_have_safe_defaults() -> None:
    """Unknown enumeration members degrade instead of raising."""
    assert portal_status("new") == "new"
    assert portal_status("something-new") == "new"
    assert portal_severity("blocker") == "critical"
    assert portal_severity("unheard-of") == "medium"


def test_portal_sla_breached_uses_recorded_flags_for_missing_snapshots() -> None:
    """A defect without an SLA snapshot is never reported as breached."""
    from td_service.repository import PortalDefectSnapshot

    snapshot = PortalDefectSnapshot(
        uuid4(),
        PROJECT_A,
        "TD-A-00",
        "no sla",
        "major",
        "p2",
        "new",
        None,
        None,
        None,
        None,
        None,
        False,
        False,
    )
    assert portal_sla_breached(snapshot, "new", NOW) is False


def test_parse_project_ids_drops_malformed_and_duplicate_entries() -> None:
    """CSV parsing is defensive and order preserving."""
    raw = f"{PROJECT_A},oops,,{PROJECT_B},{PROJECT_A}"
    assert parse_project_ids(raw) == (PROJECT_A, PROJECT_B)
    assert parse_project_ids(None) == ()


def test_parse_portal_limit_bounds() -> None:
    """Limits fall back to the default and reject out-of-range values."""
    assert parse_portal_limit(None, 5, 50) == 5
    assert parse_portal_limit("9", 5, 50) == 9
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
                "X-Platform-Permissions": f"defect:read,{CROSS_PROJECT_PERMISSION}",
            }
        )
        is True
    )


def test_http_endpoint_scopes_by_project_ids(uow: MemoryUnitOfWork) -> None:
    """The HTTP adapter honours project_ids and returns the envelope shape."""
    client = create_app(uow, config=Config()).test_client()

    response = client.get(
        f"/api/v1/portal/td-summary?project_ids={PROJECT_A}",
        headers={"X-Actor-Id": str(ACTOR), "X-Trace-Id": "trace-td"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["meta"]["trace_id"] == "trace-td"
    assert body["data"]["total"] == 9
    assert body["data"]["my_open_defects"]["count"] == 3


def test_http_endpoint_ignores_cross_project_without_permission(
    uow: MemoryUnitOfWork,
) -> None:
    """A forged cross-project header is ignored when the permission is absent."""
    client = create_app(uow, config=Config()).test_client()

    response = client.get(
        f"/api/v1/portal/td-summary?project_ids={PROJECT_A}",
        headers={
            "X-Actor-Id": str(ACTOR),
            "X-Portal-Cross-Project": "true",
            "X-Platform-Permissions": "defect:read",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["total"] == 9


def test_http_endpoint_accepts_cross_project_with_permission(
    uow: MemoryUnitOfWork,
) -> None:
    """A permitted cross-project read spans every project."""
    client = create_app(uow, config=Config()).test_client()

    response = client.get(
        "/api/v1/portal/td-summary",
        headers={
            "X-Actor-Id": str(ACTOR),
            "X-Portal-Cross-Project": "true",
            "X-Platform-Permissions": CROSS_PROJECT_PERMISSION,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["total"] == 10


def test_http_endpoint_rejects_out_of_range_limit(uow: MemoryUnitOfWork) -> None:
    """An invalid defect_limit yields a problem+json validation error."""
    client = create_app(uow, config=Config()).test_client()

    response = client.get(
        f"/api/v1/portal/td-summary?project_ids={PROJECT_A}&defect_limit=99",
        headers={"X-Actor-Id": str(ACTOR)},
    )

    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "VALIDATION_ERROR"
