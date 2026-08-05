"""Coverage for frozen plans, append-only execution and traceability APIs."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tp_service.app import create_app
from tp_service.domain import DomainError
from tp_service.domain import TestExecution as ExecutionAggregate
from tp_service.execution import (
    ManagedEnvironment,
    ManagedExecution,
    ManagedPlan,
    PlanScopeSnapshot,
    ingest_automation_json,
    ingest_junit_xml,
)
from tp_service.repository import AllowAllAuthorizer, MemoryUnitOfWork
from tp_service.service import TpService
from tp_service.traceability import TraceProjectionService


def test_plan_freeze_and_attempt_history_are_immutable() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    environment_id = uuid4()
    requirement_id = uuid4()
    case_version_id = uuid4()
    plan = ManagedPlan(uuid4(), project_id, "TP-1", actor_id)
    scope = (
        PlanScopeSnapshot(
            requirement_id,
            1,
            "a" * 64,
            case_version_id,
            environment_id,
        ),
    )
    plan.freeze(scope, {case_version_id})
    with pytest.raises(DomainError, match="immutable"):
        plan.replace_scope(())

    aggregate = ExecutionAggregate(
        uuid4(), project_id, plan.id, environment_id, actor_id
    )
    aggregate.start((case_version_id,))
    managed = ManagedExecution(aggregate, 1)
    managed.transition_attempt(case_version_id, "running")
    first = managed.transition_attempt(case_version_id, "failed", "assertion")
    with pytest.raises(DomainError, match="transition"):
        managed.transition_attempt(case_version_id, "passed")
    second = managed.correct_terminal(case_version_id, "passed")
    assert first.status == "failed"
    assert second.attempt_no == 2
    assert [item.status for item in aggregate.attempts[case_version_id]] == [
        "failed",
        "passed",
    ]


def test_result_ingestion_maps_statuses_and_rejects_unsafe_xml() -> None:
    project_id = uuid4()
    case_id = uuid4()
    payload = json.dumps(
        {
            "source": "ci",
            "external_run_ref": "run-1",
            "results": [
                {"external_case_ref": "a", "status": "passed"},
                {"external_case_ref": "a", "status": "failed"},
                {"external_case_ref": "a", "status": "skipped"},
                {"external_case_ref": "a", "status": "vendor"},
                {"external_case_ref": "missing", "status": "passed"},
            ],
        }
    ).encode()
    ingestion = ingest_automation_json(project_id, payload, {"a": case_id})
    assert ingestion.summary == {
        "passed": 1,
        "failed": 1,
        "skipped": 1,
        "unknown": 1,
        "unmapped": 1,
    }
    assert ingest_automation_json(project_id, payload, {"a": case_id}, ingestion) is ingestion
    with pytest.raises(DomainError, match="another payload"):
        ingest_automation_json(project_id, payload + b" ", {"a": case_id}, ingestion)
    with pytest.raises(DomainError, match="forbidden"):
        ingest_junit_xml(
            project_id,
            b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><testsuite/>',
            "ci",
            "run-2",
            {},
        )


def test_service_enforces_project_isolation_and_report_revisions() -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    environment = ManagedEnvironment(
        uuid4(), project_id, "QA", "test", "https://qa.example.test"
    )
    plan = ManagedPlan(uuid4(), project_id, "TP-1", actor_id)
    case_id = uuid4()
    plan.freeze(
        (
            PlanScopeSnapshot(
                uuid4(), 1, "b" * 64, case_id, environment.id
            ),
        ),
        {case_id},
    )
    aggregate = ExecutionAggregate(
        uuid4(), project_id, plan.id, environment.id, actor_id
    )
    aggregate.start((case_id,))
    execution = ManagedExecution(aggregate, 1)
    execution.transition_attempt(case_id, "running")
    execution.transition_attempt(case_id, "passed")
    uow = MemoryUnitOfWork()
    uow.environments[(project_id, environment.id)] = environment
    uow.plans[(project_id, plan.id)] = plan
    uow.executions[(project_id, aggregate.id)] = execution
    service = TpService(uow, AllowAllAuthorizer())
    with pytest.raises(DomainError) as captured:
        service.publish_report(actor_id, other_project_id, aggregate.id)
    assert captured.value.status == 404
    first = service.publish_report(actor_id, project_id, aggregate.id)
    second = service.publish_report(actor_id, project_id, aggregate.id)
    assert (first.revision, second.revision) == (1, 2)
    assert first.report.summary == second.report.summary


def test_trace_projection_is_idempotent_bounded_and_project_scoped() -> None:
    project_id = uuid4()
    requirement_id = uuid4()
    case_id = uuid4()
    event_id = uuid4()
    occurred_at = datetime.now(UTC) - timedelta(minutes=2)
    projection = TraceProjectionService()
    event = {
        "event_id": event_id,
        "project_id": project_id,
        "source_domain": "requirement",
        "source_type": "requirement",
        "source_id": requirement_id,
        "target_domain": "tp",
        "target_type": "test_case",
        "target_id": case_id,
        "link_type": "verified_by",
        "occurred_at": occurred_at.isoformat(),
    }
    assert projection.consume(event) is projection.consume(event)
    graph = projection.query(project_id, requirement_id, "forward")
    assert graph.completeness == "pass"
    assert graph.stale is True
    with pytest.raises(DomainError) as captured:
        projection.query(uuid4(), requirement_id)
    assert captured.value.status == 404


def test_trace_api_returns_rfc9457_for_cross_project_root() -> None:
    projection = TraceProjectionService()
    project_id = uuid4()
    root_id = uuid4()
    projection.consume(
        {
            "event_id": uuid4(),
            "project_id": project_id,
            "source_domain": "requirement",
            "source_type": "requirement",
            "source_id": root_id,
            "target_domain": "tp",
            "target_type": "test_case",
            "target_id": uuid4(),
            "link_type": "verified_by",
        }
    )
    client = create_app(trace_projection=projection).test_client()
    response = client.get(
        f"/api/v1/projects/{project_id}/traceability/{root_id}?direction=forward"
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["completeness"] == "pass"
    hidden = client.get(
        f"/api/v1/projects/{uuid4()}/traceability/{root_id}"
    )
    assert hidden.status_code == 404
    assert hidden.content_type == "application/problem+json"
