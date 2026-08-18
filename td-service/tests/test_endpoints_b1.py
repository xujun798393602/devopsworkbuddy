"""B1 endpoint tests for td-service (architecture §9.B)."""
from __future__ import annotations

import pytest
from uuid import uuid4

from td_service.app import create_app
from td_service.repository import MemoryUnitOfWork


def _defect_payload(**overrides):
    payload = {
        "title": "Login button unresponsive",
        "description": "Clicking login does nothing on Safari",
        "severity": "major",
        "priority": "p2",
        "defect_type": "functional",
        "expected_result": "Session starts",
        "actual_result": "Nothing happens",
    }
    payload.update(overrides)
    return payload


def _create_defect(client, project, *, severity="major"):
    payload = _defect_payload(severity=severity)
    if severity in {"blocker", "critical"}:
        payload["reproduction_steps"] = ["open page", "click login"]
    return client.post(
        f"/api/v1/projects/{project}/defects",
        json=payload,
        headers={"Idempotency-Key": str(uuid4()), "X-Actor-Id": str(uuid4())},
    )


# ---------------------------------------------------------------------------
# Listing (§9.B.1)
# ---------------------------------------------------------------------------


def test_list_defects_is_cursor_paginated():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project = uuid4()
    for _ in range(5):
        assert _create_defect(client, project).status_code == 201

    first = client.get(f"/api/v1/projects/{project}/defects?limit=2")
    assert first.status_code == 200
    body = first.json
    assert "items" in body["data"]
    assert len(body["data"]["items"]) == 2
    assert body["meta"]["has_more"] is True
    assert body["meta"]["next_cursor"]

    second = client.get(
        f"/api/v1/projects/{project}/defects?limit=2&cursor={body['meta']['next_cursor']}"
    )
    assert second.status_code == 200
    assert len(second.json["data"]["items"]) == 2
    assert second.json["meta"]["has_more"] is True

    third = client.get(
        f"/api/v1/projects/{project}/defects?limit=2&cursor={second.json['meta']['next_cursor']}"
    )
    assert third.status_code == 200
    assert len(third.json["data"]["items"]) == 1
    assert third.json["meta"]["has_more"] is False
    assert third.json["meta"]["next_cursor"] is None


# ---------------------------------------------------------------------------
# PATCH (§9.B.2)
# ---------------------------------------------------------------------------


def test_patch_defect_requires_matching_etag_and_applies():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project = uuid4()
    created = _create_defect(client, project)
    defect_id = created.json["data"]["id"]
    actor = {"X-Actor-Id": str(uuid4())}

    stale = client.patch(
        f"/api/v1/projects/{project}/defects/{defect_id}",
        json={"title": "X"},
        headers={"If-Match": '"2"', **actor},
    )
    assert stale.status_code == 412

    ok = client.patch(
        f"/api/v1/projects/{project}/defects/{defect_id}",
        json={"title": "Renamed defect"},
        headers={"If-Match": '"1"', **actor},
    )
    assert ok.status_code == 200
    assert ok.json["data"]["title"] == "Renamed defect"
    assert ok.json["data"]["version"] == 2
    assert ok.headers["ETag"] == '"2"'

    again = client.patch(
        f"/api/v1/projects/{project}/defects/{defect_id}",
        json={"title": "Y"},
        headers={"If-Match": '"1"', **actor},
    )
    assert again.status_code == 412


def test_patch_defect_rejects_unknown_field_and_bad_severity():
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project = uuid4()
    created = _create_defect(client, project)
    defect_id = created.json["data"]["id"]
    url = f"/api/v1/projects/{project}/defects/{defect_id}"
    headers = {"If-Match": '"1"', "X-Actor-Id": str(uuid4())}

    unknown = client.patch(url, json={"bogus": 1}, headers=headers)
    assert unknown.status_code == 422

    bad_severity = client.patch(url, json={"severity": "urgent"}, headers=headers)
    assert bad_severity.status_code == 422


# ---------------------------------------------------------------------------
# Severity enum (§9.B.2 / frozen five-level scale)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("severity", ["blocker", "critical", "major", "minor", "trivial"])
def test_severity_enum_is_preserved_on_create(severity):
    store = MemoryUnitOfWork()
    client = create_app(store).test_client()
    project = uuid4()
    created = _create_defect(client, project, severity=severity)
    assert created.status_code == 201
    defect_id = created.json["data"]["id"]

    fetched = client.get(f"/api/v1/projects/{project}/defects/{defect_id}")
    assert fetched.status_code == 200
    # The raw five-level enum is returned, never folded into high/medium/low.
    assert fetched.json["data"]["severity"] == severity
