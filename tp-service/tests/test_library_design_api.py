"""TP Folder, DesignSession, ReviewGate and import API tests."""
from __future__ import annotations

import io
import json
import zipfile
from uuid import uuid4

from tp_service.app import create_app
from tp_service.repository import MemoryUnitOfWork


def write_headers(actor_id: object, key: str, etag: str | None = None) -> dict[str, str]:
    values = {"X-Actor-Id": str(actor_id), "Idempotency-Key": key}
    if etag is not None:
        values["If-Match"] = etag
    return values


def safe_xmind() -> bytes:
    payload = [{"id": "sheet-1", "rootTopic": {"id": "root", "title": "Cases", "children": {"attached": [{"id": "case-1", "title": "Login works", "notes": {"plain": {"content": "Expected dashboard"}}}]}}}]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.json", json.dumps(payload))
    return output.getvalue()


def test_folder_cycle_cross_project_and_etag_are_rejected() -> None:
    uow = MemoryUnitOfWork()
    client = create_app(uow).test_client()
    actor = uuid4()
    project = uuid4()
    root = client.post(f"/api/v1/projects/{project}/test-folders", json={"name": "Root"}, headers=write_headers(actor, "f1"))
    child = client.post(f"/api/v1/projects/{project}/test-folders", json={"name": "Child", "parent_id": root.json["data"]["id"]}, headers=write_headers(actor, "f2"))
    stale = client.post(f"/api/v1/projects/{project}/test-folders/{root.json['data']['id']}/move", json={"target_parent_id": child.json["data"]["id"]}, headers=write_headers(actor, "f3", '"99"'))
    assert stale.status_code == 412
    cycle = client.post(f"/api/v1/projects/{project}/test-folders/{root.json['data']['id']}/move", json={"target_parent_id": child.json["data"]["id"]}, headers=write_headers(actor, "f4", '"1"'))
    assert cycle.status_code == 409
    hidden = client.post(f"/api/v1/projects/{uuid4()}/test-folders", json={"name": "Hidden", "parent_id": root.json["data"]["id"]}, headers=write_headers(actor, "f5"))
    assert hidden.status_code == 404


def test_design_stages_require_human_gates_and_import_safe_xmind() -> None:
    uow = MemoryUnitOfWork()
    client = create_app(uow).test_client()
    creator = uuid4()
    reviewer = uuid4()
    project = uuid4()
    folder = client.post(f"/api/v1/projects/{project}/test-folders", json={"name": "Generated"}, headers=write_headers(creator, "folder"))
    created = client.post(f"/api/v1/projects/{project}/test-design-sessions", json={"requirement_snapshot_refs": ["REQ-1@rev-2#abc"], "target_folder_id": folder.json["data"]["id"]}, headers=write_headers(creator, "session"))
    session_id = created.json["data"]["id"]
    premature = client.post(f"/api/v1/projects/{project}/test-design-sessions/{session_id}/stage-runs", json={"stage": "design"}, headers=write_headers(creator, "premature", created.headers["ETag"]))
    assert premature.status_code == 409
    current = created
    for index, stage in enumerate(("analysis", "design", "cases"), start=1):
        run = client.post(f"/api/v1/projects/{project}/test-design-sessions/{session_id}/stage-runs", json={"stage": stage}, headers=write_headers(creator, f"run-{index}", current.headers["ETag"]))
        assert run.status_code == 200
        assert run.json["data"]["runs"][-1]["provider"] == "mock"
        run_id = run.json["data"]["runs"][-1]["id"]
        self_gate = client.post(f"/api/v1/projects/{project}/test-design-sessions/{session_id}/stage-runs/{run_id}/review-gates", json={"decision": "approved"}, headers=write_headers(creator, f"self-{index}", run.headers["ETag"]))
        assert self_gate.status_code == 403
        current = client.post(f"/api/v1/projects/{project}/test-design-sessions/{session_id}/stage-runs/{run_id}/review-gates", json={"decision": "approved"}, headers=write_headers(reviewer, f"gate-{index}", run.headers["ETag"]))
        assert current.status_code == 200
    imported = client.post(f"/api/v1/projects/{project}/test-design-sessions/{session_id}/imports", data={"conflict_strategy": "create_new", "file": (io.BytesIO(safe_xmind()), "cases.xmind")}, headers=write_headers(creator, "import", current.headers["ETag"]), content_type="multipart/form-data")
    assert imported.status_code == 200
    assert imported.json["data"]["validation_summary"] == {"case_count": 1, "node_count": 2}
    assert uow.sessions[(project, uuid4())] if False else len(uow.import_batches) == 1
