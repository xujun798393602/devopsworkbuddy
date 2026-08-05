"""Parameterized HTTP idempotency contract tests for every TP write route."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from flask.testing import FlaskClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tp_service.app import create_app
from tp_service.persistence import Base
from tp_service.repository import SqlAlchemyUnitOfWork


@dataclass(frozen=True)
class WriteCase:
    """A concrete request for one contract-protected POST operation."""

    name: str
    path: str
    operation: str
    payload: dict[str, Any]
    multipart: bool = False
    raw_body: bytes | None = None


def _cases(project_id: UUID) -> tuple[WriteCase, ...]:
    folder_id = uuid4()
    session_id = uuid4()
    run_id = uuid4()
    plan_id = uuid4()
    execution_id = uuid4()
    return (
        WriteCase("create-folder", f"/api/v1/projects/{project_id}/test-folders", "test-folder:create", {"name": "Regression"}),
        WriteCase("move-folder", f"/api/v1/projects/{project_id}/test-folders/{folder_id}/move", "test-folder:move", {"folder_id": str(folder_id), "target_parent_id": None}),
        WriteCase("create-design-session", f"/api/v1/projects/{project_id}/test-design-sessions", "test-design-session:create", {"requirement_snapshot_refs": [], "target_folder_id": str(uuid4())}),
        WriteCase("run-stage", f"/api/v1/projects/{project_id}/test-design-sessions/{session_id}/stage-runs", "test-design-stage:run", {"session_id": str(session_id), "stage": "analysis"}),
        WriteCase("review-gate", f"/api/v1/projects/{project_id}/test-design-sessions/{session_id}/stage-runs/{run_id}/review-gates", "test-design-gate:review", {"session_id": str(session_id), "run_id": str(run_id), "decision": "approved"}),
        WriteCase("import-xmind", f"/api/v1/projects/{project_id}/test-design-sessions/{session_id}/imports", "test-design:xmind-import", {"session_id": str(session_id), "file_sha256": hashlib.sha256(b"xmind").hexdigest(), "conflict_strategy": "create_new"}, multipart=True),
        WriteCase("create-environment", f"/api/v1/projects/{project_id}/test-environments", "test-environment:create", {"name": "QA", "classification": "test", "base_url": "https://qa.example.test"}),
        WriteCase("create-plan", f"/api/v1/projects/{project_id}/test-plans", "test-plan:create", {"owner_id": str(uuid4()), "business_no": "TP-1"}),
        WriteCase("freeze-plan", f"/api/v1/projects/{project_id}/test-plans/{plan_id}/freeze", "test-plan:freeze", {"scope": [], "valid_case_versions": []}),
        WriteCase("create-execution", f"/api/v1/projects/{project_id}/test-executions", "test-execution:create", {"plan_id": str(uuid4()), "environment_id": str(uuid4()), "assignee_id": str(uuid4())}),
        WriteCase("start-execution", f"/api/v1/projects/{project_id}/test-executions/{execution_id}/start", "test-execution:start", {}),
        WriteCase("ingest-results", f"/api/v1/projects/{project_id}/automation-result-ingestions", "automation-result:ingest", {"body_sha256": hashlib.sha256(b"results").hexdigest(), "case_mappings": {}, "content_type": "application/json", "source": "junit", "external_run_ref": "run-1"}, raw_body=b"results"),
    )


def _fingerprint(operation: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        {"operation": operation, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _post(client: FlaskClient, case: WriteCase, headers: dict[str, str]) -> Any:
    request_headers = dict(headers)
    if case.multipart:
        return client.post(
            case.path,
            data={
                "file": (BytesIO(b"xmind"), "suite.xmind"),
                "conflict_strategy": "create_new",
            },
            headers=request_headers,
        )
    if case.raw_body is not None:
        request_headers.update(
            {
                "Content-Type": "application/json",
                "X-Case-Mappings": "{}",
                "X-Result-Source": "junit",
                "X-External-Run-Ref": "run-1",
            }
        )
        return client.post(case.path, data=case.raw_body, headers=request_headers)
    return client.post(case.path, json=case.payload, headers=request_headers)


@pytest.mark.parametrize("case_index", range(12))
def test_each_post_requires_idempotency_key(case_index: int) -> None:
    """Every protected write rejects a missing key before domain mutation."""
    project_id = uuid4()
    case = _cases(project_id)[case_index]
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = create_app(SqlAlchemyUnitOfWork(Session(engine))).test_client()

    response = _post(client, case, {"X-Actor-Id": str(uuid4())})

    assert response.status_code == 400
    assert response.json["code"] == "IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.parametrize("case_index", range(12))
def test_each_post_rejects_same_key_with_different_body(case_index: int) -> None:
    """Durable SQL records reject fingerprint conflicts for every write route."""
    project_id = uuid4()
    actor_id = uuid4()
    case = _cases(project_id)[case_index]
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    seed = SqlAlchemyUnitOfWork(Session(engine))
    seed.idempotency[(project_id, actor_id, "shared-key")] = (
        "0" * 64,
        {"data": {"seeded": True}, "meta": {"trace_id": "seed"}},
        200,
    )
    seed.commit()
    client = create_app(SqlAlchemyUnitOfWork(Session(engine))).test_client()

    response = _post(
        client,
        case,
        {"X-Actor-Id": str(actor_id), "Idempotency-Key": "shared-key"},
    )

    assert response.status_code == 409
    assert response.json["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize("case_index", range(12))
def test_same_key_is_scoped_by_project_in_sql_uow(case_index: int) -> None:
    """A record in another project must never be replayed or conflict."""
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    case = _cases(project_id)[case_index]
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    seed = SqlAlchemyUnitOfWork(Session(engine))
    seed.idempotency[(other_project_id, actor_id, "shared-key")] = (
        _fingerprint(case.operation, case.payload),
        {"data": {"wrong_project": True}, "meta": {"trace_id": "seed"}},
        299,
    )
    seed.commit()
    client = create_app(SqlAlchemyUnitOfWork(Session(engine))).test_client()

    response = _post(
        client,
        case,
        {"X-Actor-Id": str(actor_id), "Idempotency-Key": "shared-key"},
    )

    assert response.status_code != 299
    assert not (response.status_code == 409 and response.json["code"] == "IDEMPOTENCY_KEY_REUSED")
