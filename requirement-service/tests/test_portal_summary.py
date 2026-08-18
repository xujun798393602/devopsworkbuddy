"""Portal aggregation endpoint tests for requirement-service."""

from __future__ import annotations

from uuid import UUID, uuid4

from requirement_service.app import create_app, parse_project_ids, portal_cross_project
from requirement_service.domain import Baseline, Requirement, RequirementStatus, RequirementType
from requirement_service.repository import MemoryUnitOfWork

PROJECT_A = UUID("11111111-1111-4111-8111-111111111111")
PROJECT_B = UUID("22222222-2222-4222-8222-222222222222")
ACTOR = UUID("33333333-3333-4333-8333-333333333333")
CROSS_PROJECT_HEADERS = {
    "X-Actor-Id": str(ACTOR),
    "X-Portal-Cross-Project": "true",
    "X-Platform-Permissions": "portal:cross-project-view",
}


def _requirement(
    project_id: UUID, business_no: str, status: RequirementStatus, title: str = "支持批量退款"
) -> Requirement:
    requirement = Requirement(
        id=uuid4(),
        project_id=project_id,
        business_no=business_no,
        title=title,
        type=RequirementType.USER_STORY,
        owner_id=ACTOR,
        release_version_id=uuid4(),
    )
    requirement.status = status
    return requirement


def _store() -> MemoryUnitOfWork:
    store = MemoryUnitOfWork()
    rows = [
        _requirement(PROJECT_A, "REQ-001", RequirementStatus.DRAFT),
        _requirement(PROJECT_A, "REQ-002", RequirementStatus.IN_REVIEW),
        _requirement(PROJECT_A, "REQ-003", RequirementStatus.IN_REVIEW),
        _requirement(PROJECT_A, "REQ-004", RequirementStatus.APPROVED),
        _requirement(PROJECT_A, "REQ-005", RequirementStatus.ACTIVE),
        _requirement(PROJECT_A, "REQ-006", RequirementStatus.REJECTED),
        _requirement(PROJECT_A, "REQ-007", RequirementStatus.COMPLETED),
        _requirement(PROJECT_A, "REQ-008", RequirementStatus.CANCELED),
        _requirement(PROJECT_B, "REQ-101", RequirementStatus.IN_REVIEW),
    ]
    for row in rows:
        store.requirements[(row.project_id, row.id)] = row
    active = Baseline(uuid4(), PROJECT_A, "BL-001", uuid4(), ((uuid4(), "hash"),), "active")
    draft = Baseline(uuid4(), PROJECT_A, "BL-002", uuid4(), ((uuid4(), "hash"),), "draft")
    other = Baseline(uuid4(), PROJECT_B, "BL-101", uuid4(), ((uuid4(), "hash"),), "active")
    for baseline in (active, draft, other):
        store.baselines[(baseline.project_id, baseline.id)] = baseline
    return store


def _client(store: MemoryUnitOfWork):
    return create_app(store).test_client()


def test_summary_maps_domain_lifecycle_onto_frozen_status_keys() -> None:
    response = _client(_store()).get(
        f"/api/v1/portal/requirement-summary?project_ids={PROJECT_A}",
        headers={"X-Actor-Id": str(ACTOR)},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 8
    assert data["by_status"] == {
        "draft": 1,
        "reviewing": 2,
        "approved": 2,
        "rejected": 1,
        "archived": 2,
    }
    assert data["baseline_total"] == 1


def test_pending_reviews_are_scoped_shaped_and_capped() -> None:
    response = _client(_store()).get(
        f"/api/v1/portal/requirement-summary?project_ids={PROJECT_A}&review_limit=1",
        headers={"X-Actor-Id": str(ACTOR)},
    )
    block = response.get_json()["data"]["pending_reviews"]
    assert block["count"] == 2
    assert len(block["items"]) == 1
    assert block["items"][0] == {
        "id": block["items"][0]["id"],
        "project_id": str(PROJECT_A),
        "business_no": "REQ-002",
        "title": "支持批量退款",
        "status": "reviewing",
        "updated_at": None,
    }


def test_unknown_project_scope_returns_structured_zeroes() -> None:
    response = _client(_store()).get(f"/api/v1/portal/requirement-summary?project_ids={uuid4()}")
    data = response.get_json()["data"]
    assert data["total"] == 0
    assert data["baseline_total"] == 0
    assert data["pending_reviews"] == {"count": 0, "items": []}
    assert set(data["by_status"]) == {"draft", "reviewing", "approved", "rejected", "archived"}


def test_empty_scope_without_permission_never_leaks_the_platform() -> None:
    response = _client(_store()).get(
        "/api/v1/portal/requirement-summary",
        headers={"X-Actor-Id": str(ACTOR), "X-Portal-Cross-Project": "true"},
    )
    assert response.get_json()["data"]["total"] == 0


def test_cross_project_with_permission_covers_every_project() -> None:
    response = _client(_store()).get(
        "/api/v1/portal/requirement-summary", headers=CROSS_PROJECT_HEADERS
    )
    data = response.get_json()["data"]
    assert data["total"] == 9
    assert data["by_status"]["reviewing"] == 3
    assert data["baseline_total"] == 2


def test_invalid_review_limit_is_rejected() -> None:
    response = _client(_store()).get("/api/v1/portal/requirement-summary?review_limit=0")
    assert response.status_code == 422
    assert response.content_type == "application/problem+json"


def test_project_ids_parser_drops_malformed_entries_and_deduplicates() -> None:
    assert parse_project_ids(None) == ()
    assert parse_project_ids(" , ") == ()
    assert parse_project_ids(f"{PROJECT_A}, not-a-uuid ,{PROJECT_A}") == (str(PROJECT_A),)


def test_cross_project_header_requires_the_permission_point() -> None:
    assert portal_cross_project({"X-Portal-Cross-Project": "true"}) is False
    assert (
        portal_cross_project(
            {"X-Portal-Cross-Project": "true", "X-Platform-Permissions": "audit.read"}
        )
        is False
    )
    assert portal_cross_project(CROSS_PROJECT_HEADERS) is True
