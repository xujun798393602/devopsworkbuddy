"""HTTP contract tests for the portal test-cases and test-plans endpoints.

Covers architecture document §9.C: test-cases list/create/get/PATCH/versions
and test-plans list/get/generic transitions. Routes are exercised through the
Flask test client backed by an in-memory SQLite unit of work, mirroring the
existing idempotency contract suite.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from flask.testing import FlaskClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tp_service.app import create_app
from tp_service.repository import MemoryUnitOfWork


def _client() -> FlaskClient:
    return create_app(MemoryUnitOfWork()).test_client()


def _headers(actor_id: UUID | None = None) -> dict[str, str]:
    headers = {"Idempotency-Key": str(uuid4())}
    if actor_id is not None:
        headers["X-Actor-Id"] = str(actor_id)
    return headers


def _make_folder(client: FlaskClient, project_id: UUID) -> UUID:
    actor_id = uuid4()
    body = {"name": "Regression", "parent_id": None}
    response = client.post(
        f"/api/v1/projects/{project_id}/test-folders",
        json=body,
        headers=_headers(actor_id),
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return UUID(response.json["data"]["id"])


def test_create_and_get_test_case() -> None:
    client = _client()
    project_id = uuid4()
    folder_id = _make_folder(client, project_id)
    actor_id = uuid4()

    create = client.post(
        f"/api/v1/projects/{project_id}/test-cases",
        json={
            "folder_id": str(folder_id),
            "title": "Login happy path",
            "owner_id": str(actor_id),
            "type": "functional",
            "priority": "p1",
            "automation_mode": "manual",
            "requirement_refs": [],
        },
        headers=_headers(actor_id),
    )
    assert create.status_code == 201, create.get_data(as_text=True)
    body = create.json["data"]
    assert body["title"] == "Login happy path"
    assert body["type"] == "functional"
    assert body["status"] == "draft"
    assert body["current_version_id"] is None
    case_id = UUID(body["id"])
    assert create.headers["ETag"] == f'"{body["version"]}"'

    fetched = client.get(f"/api/v1/projects/{project_id}/test-cases/{case_id}")
    assert fetched.status_code == 200
    assert fetched.json["data"]["id"] == str(case_id)
    assert fetched.headers["ETag"] == f'"{body["version"]}"'


def test_list_test_cases_cursor_pagination() -> None:
    client = _client()
    project_id = uuid4()
    folder_id = _make_folder(client, project_id)
    actor_id = uuid4()
    created_ids: list[str] = []
    for index in range(3):
        response = client.post(
            f"/api/v1/projects/{project_id}/test-cases",
            json={
                "folder_id": str(folder_id),
                "title": f"Case {index}",
                "owner_id": str(actor_id),
                "type": "functional",
                "priority": "p2",
                "automation_mode": "manual",
                "requirement_refs": [],
            },
            headers=_headers(actor_id),
        )
        assert response.status_code == 201
        created_ids.append(response.json["data"]["id"])

    first = client.get(f"/api/v1/projects/{project_id}/test-cases?limit=2")
    assert first.status_code == 200
    page = first.json["data"]["items"]
    assert len(page) == 2
    assert first.json["meta"]["has_more"] is True
    assert first.json["meta"]["next_cursor"] is not None

    second = client.get(
        f"/api/v1/projects/{project_id}/test-cases?limit=2&cursor={first.json['meta']['next_cursor']}"
    )
    assert second.status_code == 200
    assert len(second.json["data"]["items"]) == 1
    assert second.json["meta"]["has_more"] is False


def test_patch_test_case_requires_matching_if_match() -> None:
    client = _client()
    project_id = uuid4()
    folder_id = _make_folder(client, project_id)
    actor_id = uuid4()
    created = client.post(
        f"/api/v1/projects/{project_id}/test-cases",
        json={
            "folder_id": str(folder_id),
            "title": "Before",
            "owner_id": str(actor_id),
            "type": "functional",
            "priority": "p2",
            "automation_mode": "manual",
            "requirement_refs": [],
        },
        headers=_headers(actor_id),
    )
    case_id = UUID(created.json["data"]["id"])
    etag = created.headers["ETag"]

    without_match = client.patch(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}",
        json={"title": "After"},
        headers=_headers(actor_id),
    )
    assert without_match.status_code == 412
    assert without_match.json["code"] == "PRECONDITION_FAILED"

    with_match = client.patch(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}",
        json={"title": "After", "priority": "p0"},
        headers={**_headers(actor_id), "If-Match": etag},
    )
    assert with_match.status_code == 200, with_match.get_data(as_text=True)
    assert with_match.json["data"]["title"] == "After"
    assert with_match.json["data"]["priority"] == "p0"
    assert with_match.headers["ETag"] != etag


def test_create_case_version_publishes_and_lists() -> None:
    client = _client()
    project_id = uuid4()
    folder_id = _make_folder(client, project_id)
    actor_id = uuid4()
    created = client.post(
        f"/api/v1/projects/{project_id}/test-cases",
        json={
            "folder_id": str(folder_id),
            "title": "Versioned case",
            "owner_id": str(actor_id),
            "type": "functional",
            "priority": "p2",
            "automation_mode": "manual",
            "requirement_refs": [],
        },
        headers=_headers(actor_id),
    )
    case_id = UUID(created.json["data"]["id"])

    version = client.post(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/versions",
        json={
            "source": "manual",
            "steps": [
                {"sequence": 1, "action": "Open app", "expected": "Home shown", "test_data": ""},
            ],
        },
        headers=_headers(actor_id),
    )
    assert version.status_code == 201, version.get_data(as_text=True)
    assert version.json["data"]["version_no"] == 1
    assert version.json["data"]["steps"][0]["action"] == "Open app"

    fetched = client.get(f"/api/v1/projects/{project_id}/test-cases/{case_id}")
    assert fetched.json["data"]["current_version_id"] == version.json["data"]["id"]
    assert fetched.json["data"]["status"] == "active"

    versions = client.get(f"/api/v1/projects/{project_id}/test-cases/{case_id}/versions")
    assert versions.status_code == 200
    assert len(versions.json["data"]["items"]) == 1


def test_test_plans_list_get_and_transition() -> None:
    client = _client()
    project_id = uuid4()
    actor_id = uuid4()

    created = client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        json={"owner_id": str(actor_id), "business_no": "TP-1"},
        headers=_headers(actor_id),
    )
    assert created.status_code == 201
    plan_id = UUID(created.json["data"]["id"])

    listed = client.get(f"/api/v1/projects/{project_id}/test-plans")
    assert listed.status_code == 200
    assert any(item["id"] == str(plan_id) for item in listed.json["data"]["items"])

    fetched = client.get(f"/api/v1/projects/{project_id}/test-plans/{plan_id}")
    assert fetched.status_code == 200
    etag = fetched.headers["ETag"]
    assert fetched.json["data"]["status"] == "draft"

    bad = client.post(
        f"/api/v1/projects/{project_id}/test-plans/{plan_id}/transitions",
        json={"action": "not_a_real_action"},
        headers={**_headers(actor_id), "If-Match": etag},
    )
    assert bad.status_code == 422
    assert bad.json["code"] == "INVALID_PLAN_TRANSITION"

    canceled = client.post(
        f"/api/v1/projects/{project_id}/test-plans/{plan_id}/transitions",
        json={"action": "cancel"},
        headers={**_headers(actor_id), "If-Match": etag},
    )
    assert canceled.status_code == 200, canceled.get_data(as_text=True)
    assert canceled.json["data"]["status"] == "canceled"
