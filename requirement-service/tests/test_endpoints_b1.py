"""B1 endpoint tests for requirement-service (architecture §9.A)."""
from __future__ import annotations

from uuid import uuid4

import pytest

from requirement_service.app import create_app
from requirement_service.domain import (
    Requirement,
    RequirementRevision,
    RequirementStatus,
    RequirementType,
)
from requirement_service.repository import MemoryUnitOfWork


def _seed(
    store: MemoryUnitOfWork,
    *,
    project: object | None = None,
    status: RequirementStatus = RequirementStatus.DRAFT,
    version: int = 1,
    baseline_status: str = "unbaselined",
    business_no: str = "REQ-SEED",
) -> tuple:
    """Plant a requirement directly into the store for transition tests."""
    if project is None:
        project = uuid4()
    requirement = Requirement(
        id=uuid4(),
        project_id=project,
        business_no=business_no,
        title="Seeded requirement",
        type=RequirementType.USER_STORY,
        owner_id=uuid4(),
        release_version_id=uuid4(),
        description="A seeded requirement for endpoint tests",
        acceptance_criteria=[{"id": "a", "given": "g", "when": "w", "then": "t"}],
        status=status,
        version=version,
        baseline_status=baseline_status,
    )
    store.requirements[(project, requirement.id)] = requirement
    return project, requirement


def _create_requirement(client, project, actor):
    payload = {
        "title": "Checkout",
        "type": "user_story",
        "owner_id": str(uuid4()),
        "release_version_id": str(uuid4()),
        "acceptance_criteria": [{"id": "a", "given": "g", "when": "w", "then": "t"}],
    }
    response = client.post(
        f"/api/v1/projects/{project}/requirements",
        json=payload,
        headers={"Idempotency-Key": str(uuid4()), "X-Actor-Id": str(actor)},
    )
    return response


# ---------------------------------------------------------------------------
# Listing (§9.A.1)
# ---------------------------------------------------------------------------


def test_list_requirements_is_cursor_paginated():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project = uuid4()
    for index in range(1, 6):
        _seed(store, project=project, status=RequirementStatus.DRAFT, business_no=f"REQ-{index:03d}")

    first = client.get(f"/api/v1/projects/{project}/requirements?limit=2")
    assert first.status_code == 200
    body = first.json
    assert "items" in body["data"]
    assert len(body["data"]["items"]) == 2
    assert body["meta"]["has_more"] is True
    assert body["meta"]["next_cursor"]

    cursor = body["meta"]["next_cursor"]
    second = client.get(
        f"/api/v1/projects/{project}/requirements?limit=2&cursor={cursor}"
    )
    assert second.status_code == 200
    assert len(second.json["data"]["items"]) == 2
    assert second.json["meta"]["has_more"] is True

    third = client.get(
        f"/api/v1/projects/{project}/requirements?limit=2&cursor={second.json['meta']['next_cursor']}"
    )
    assert third.status_code == 200
    assert len(third.json["data"]["items"]) == 1
    assert third.json["meta"]["has_more"] is False
    assert third.json["meta"]["next_cursor"] is None

    # Items are ordered by business_no.
    all_ids = [item["business_no"] for item in first.json["data"]["items"]]
    assert all_ids == sorted(all_ids)


def test_list_requirement_items_carry_full_detail_fields():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project, requirement = _seed(store, business_no="REQ-DETAIL")
    response = client.get(
        f"/api/v1/projects/{project}/requirements/{requirement.id}"
    )
    assert response.status_code == 200
    data = response.json["data"]
    for field in (
        "id",
        "project_id",
        "business_no",
        "title",
        "type",
        "status",
        "priority",
        "owner_id",
        "release_version_id",
        "parent_id",
        "description",
        "acceptance_criteria",
        "current_revision",
        "baseline_status",
        "version",
    ):
        assert field in data
    # created_at/updated_at are intentionally null until a migration lands.
    assert data["created_at"] is None
    assert data["updated_at"] is None
    assert response.headers["ETag"] == f'"{requirement.version}"'


# ---------------------------------------------------------------------------
# PATCH (§9.A.2)
# ---------------------------------------------------------------------------


def test_patch_requires_matching_etag_and_applies():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project, requirement = _seed(store)
    actor = uuid4()
    url = f"/api/v1/projects/{project}/requirements/{requirement.id}"
    headers = {"X-Actor-Id": str(actor)}

    # Wrong version -> 412.
    stale = client.patch(url, json={"title": "X"}, headers={**headers, "If-Match": '"2"'})
    assert stale.status_code == 412

    # Correct version -> 200 and version bumped.
    ok = client.patch(url, json={"title": "Renamed"}, headers={**headers, "If-Match": '"1"'})
    assert ok.status_code == 200
    assert ok.json["data"]["title"] == "Renamed"
    assert ok.json["data"]["version"] == 2
    assert ok.headers["ETag"] == '"2"'

    # Now the previous token is stale -> 412 again.
    again = client.patch(url, json={"title": "Y"}, headers={**headers, "If-Match": '"1"'})
    assert again.status_code == 412


def test_patch_rejects_unknown_field():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project, requirement = _seed(store)
    actor = uuid4()
    response = client.patch(
        f"/api/v1/projects/{project}/requirements/{requirement.id}",
        json={"not_a_field": 1},
        headers={"X-Actor-Id": str(actor), "If-Match": '"1"'},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Transitions (§9.A.3)
# ---------------------------------------------------------------------------


TRANSITION_CASES = [
    ("submit_review", RequirementStatus.DRAFT, {}, RequirementStatus.IN_REVIEW),
    ("approve", RequirementStatus.IN_REVIEW, {"approved_review": True}, RequirementStatus.APPROVED),
    ("reject", RequirementStatus.IN_REVIEW, {}, RequirementStatus.REJECTED),
    ("return_to_draft", RequirementStatus.REJECTED, {}, RequirementStatus.DRAFT),
    ("activate", RequirementStatus.APPROVED, {"baselined": True}, RequirementStatus.ACTIVE),
    ("complete", RequirementStatus.ACTIVE, {"completion_evidence": True}, RequirementStatus.COMPLETED),
    ("cancel", RequirementStatus.ACTIVE, {}, RequirementStatus.CANCELED),
]


@pytest.mark.parametrize("action,start,extra,expected", TRANSITION_CASES)
def test_transition_each_action(action, start, extra, expected):
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project, requirement = _seed(store, status=start)
    actor = uuid4()
    before_version = requirement.version
    response = client.post(
        f"/api/v1/projects/{project}/requirements/{requirement.id}/transitions",
        json={"action": action, **extra},
        headers={"X-Actor-Id": str(actor), "If-Match": f'"{before_version}"'},
    )
    assert response.status_code == 200, response.json
    assert response.json["data"]["status"] == expected.value
    assert response.headers["ETag"] == f'"{before_version + 1}"'


def test_transition_reopen_requires_reason():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project, requirement = _seed(store, status=RequirementStatus.COMPLETED)
    actor = uuid4()
    url = f"/api/v1/projects/{project}/requirements/{requirement.id}/transitions"
    headers = {"X-Actor-Id": str(actor), "If-Match": f'"{requirement.version}"'}

    missing = client.post(url, json={"action": "reopen", "privileged": True}, headers=headers)
    assert missing.status_code == 422

    with_reason = client.post(
        url,
        json={"action": "reopen", "privileged": True, "reason": "customer escalation"},
        headers=headers,
    )
    assert with_reason.status_code == 200
    assert with_reason.json["data"]["status"] == RequirementStatus.ACTIVE.value


def test_transition_rejects_unknown_action():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project, requirement = _seed(store)
    response = client.post(
        f"/api/v1/projects/{project}/requirements/{requirement.id}/transitions",
        json={"action": "explode"},
        headers={"X-Actor-Id": str(uuid4())},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Reviews (§9.A.4)
# ---------------------------------------------------------------------------


def test_create_review_and_decide():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    created = _create_requirement(client, uuid4(), uuid4())
    project = created.json["data"]["project_id"]
    requirement_id = created.json["data"]["id"]
    actor = uuid4()
    reviewer = uuid4()

    created_review = client.post(
        f"/api/v1/projects/{project}/requirements/{requirement_id}/reviews",
        json={"reviewer_ids": [str(reviewer)], "note": "please review"},
        headers={"X-Actor-Id": str(actor)},
    )
    assert created_review.status_code == 201
    review_id = created_review.json["data"]["id"]

    decision = client.post(
        f"/api/v1/projects/{project}/requirements/{requirement_id}"
        f"/reviews/{review_id}/decisions",
        json={"reviewer_id": str(reviewer), "decision": "approved", "comments": "lgtm"},
        headers={"X-Actor-Id": str(reviewer)},
    )
    assert decision.status_code == 200
    assert decision.json["data"]["status"] == "approved"


def test_review_forbids_self_review():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    created = _create_requirement(client, uuid4(), uuid4())
    project = created.json["data"]["project_id"]
    requirement_id = created.json["data"]["id"]
    actor = uuid4()

    response = client.post(
        f"/api/v1/projects/{project}/requirements/{requirement_id}/reviews",
        json={"reviewer_ids": [str(actor)]},
        headers={"X-Actor-Id": str(actor)},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Baselines (§9.A.5)
# ---------------------------------------------------------------------------


def test_create_and_activate_baseline():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    created = _create_requirement(client, uuid4(), uuid4())
    project = created.json["data"]["project_id"]
    requirement_id = created.json["data"]["id"]
    actor = uuid4()

    created_baseline = client.post(
        f"/api/v1/projects/{project}/requirement-baselines",
        json={
            "baseline_no": "BL-1",
            "release_version_id": str(uuid4()),
            "revision_refs": [{"requirement_id": str(requirement_id), "revision_no": 1}],
        },
        headers={"X-Actor-Id": str(actor)},
    )
    assert created_baseline.status_code == 201
    baseline_id = created_baseline.json["data"]["id"]

    activated = client.post(
        f"/api/v1/projects/{project}/requirement-baselines/{baseline_id}/activate",
        headers={"X-Actor-Id": str(actor)},
    )
    assert activated.status_code == 200
    assert activated.json["data"]["status"] == "active"


# ---------------------------------------------------------------------------
# Change requests (§9.A.6)
# ---------------------------------------------------------------------------


def test_create_and_transition_change_request():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project, requirement = _seed(store)
    revision = RequirementRevision.create(requirement.id, 1, requirement.snapshot())
    store.revisions[requirement.id] = [revision]
    actor = uuid4()
    base = f"/api/v1/projects/{project}/requirements/{requirement.id}"

    created = client.post(
        f"{base}/change-requests",
        json={
            "base_revision_id": str(revision.id),
            "proposed_patch": {"title": "Patched via CR"},
        },
        headers={"X-Actor-Id": str(actor)},
    )
    assert created.status_code == 201
    change_id = created.json["data"]["id"]

    def transition(action):
        return client.post(
            f"{base}/change-requests/{change_id}/transitions",
            json={"action": action},
            headers={"X-Actor-Id": str(actor)},
        )

    assert transition("submit").status_code == 200
    assert transition("approve").status_code == 200
    applied = transition("apply")
    assert applied.status_code == 200
    assert applied.json["data"]["status"] == "applied"

    # The governed field is now applied to the requirement.
    refreshed = client.get(f"{base}")
    assert refreshed.json["data"]["title"] == "Patched via CR"


def test_change_request_rejects_unsupported_field():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project, requirement = _seed(store)
    revision = RequirementRevision.create(requirement.id, 1, requirement.snapshot())
    store.revisions[requirement.id] = [revision]
    actor = uuid4()
    base = f"/api/v1/projects/{project}/requirements/{requirement.id}"

    response = client.post(
        f"{base}/change-requests",
        json={
            "base_revision_id": str(revision.id),
            "proposed_patch": {"tags": ["x"]},
        },
        headers={"X-Actor-Id": str(actor)},
    )
    assert response.status_code == 422
