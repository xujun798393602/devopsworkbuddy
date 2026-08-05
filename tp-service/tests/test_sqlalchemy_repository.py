"""TP normalized SQLAlchemy UoW tests."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tp_service.app import create_app
from tp_service.config import Config
from tp_service.domain import DesignSession, DomainError, ReviewGate, StageRun
from tp_service.domain import TestCase as Case
from tp_service.domain import TestCaseVersion as CaseVersion
from tp_service.domain import TestExecution as Execution
from tp_service.domain import TestFolder as Folder
from tp_service.domain import TestReport as Report
from tp_service.domain import TestStep as Step
from tp_service.execution import (
    AutomationIngestion,
    AutomationResultItem,
    ManagedEnvironment,
    ManagedExecution,
    ManagedPlan,
    PlanScopeSnapshot,
    PublishedReport,
)
from tp_service.persistence import Base, OutboxEventRow
from tp_service.repository import SqlAlchemyUnitOfWork
from tp_service.traceability import TraceabilityLink, TraceEndpoint


def test_sqlalchemy_uow_round_trips_normalized_core_and_outbox() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    project_id = uuid4()
    actor_id = uuid4()
    folder = Folder(uuid4(), project_id, "Regression")
    case = Case(uuid4(), project_id, "TC-1", folder.id, "Login", actor_id)
    version = CaseVersion.create(
        case.id, 1, [Step(1, "Open login", "Form appears")], "manual"
    )
    case.publish(version)
    design = DesignSession(uuid4(), project_id, actor_id, ("REQ-1@1",), folder.id)
    run = StageRun(uuid4(), "analysis", 1, "a" * 64, "completed", output_hash="b" * 64)
    design.runs.append(run)
    gate = ReviewGate(
        uuid4(),
        run.id,
        uuid4(),
        "approved",
        True,
        "Reviewed production acceptance criteria",
        datetime.now(UTC),
    )
    design.review_gates.append(gate)
    design.approved_stages.add("analysis")
    environment = ManagedEnvironment(
        uuid4(), project_id, "QA", "test", "https://qa.example.test"
    )
    scope = PlanScopeSnapshot(uuid4(), 1, "c" * 64, version.id, environment.id)
    plan = ManagedPlan(uuid4(), project_id, "PLAN-1", actor_id, "ready", (scope,), "d" * 64, 2)
    aggregate = Execution(
        uuid4(), project_id, plan.id, environment.id, actor_id
    )
    aggregate.start((version.id,))
    execution = ManagedExecution(aggregate, 1)
    report = PublishedReport(
        Report(uuid4(), aggregate.id, actor_id, {"passed": 1}, "e" * 64),
        project_id,
        1,
    )
    ingestion = AutomationIngestion(
        uuid4(),
        project_id,
        "ci",
        "run-1",
        "f" * 64,
        (AutomationResultItem("TC-1", "passed", version.id, 20),),
    )
    source = TraceEndpoint(project_id, "requirement", "requirement", uuid4(), 1)
    target = TraceEndpoint(project_id, "tp", "test_case", case.id, 2)
    link = TraceabilityLink(
        uuid4(), source, target, "verified_by", uuid4(), datetime.now(UTC)
    )

    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        uow.folders[(project_id, folder.id)] = folder
        uow.cases[(project_id, case.id)] = case
        uow.case_versions[case.id] = [version]
        uow.sessions[(project_id, design.id)] = design
        uow.environments[(project_id, environment.id)] = environment
        uow.plans[(project_id, plan.id)] = plan
        uow.executions[(project_id, aggregate.id)] = execution
        uow.reports[(project_id, aggregate.id)] = [report]
        uow.ingestions[(project_id, ingestion.source, ingestion.external_run_ref)] = ingestion
        uow.traceability_links[link.id] = link
        uow.idempotency[(project_id, actor_id, "key-1")] = (
            "0" * 64,
            {"data": {"id": str(folder.id)}},
            201,
        )
        uow.outbox.append(
            {"event_type": "TestFolder.Created", "project_id": str(project_id)}
        )
        uow.commit()

    with Session(engine) as session:
        loaded = SqlAlchemyUnitOfWork(session)
        assert loaded.folders[(project_id, folder.id)].name == "Regression"
        assert loaded.cases[(project_id, case.id)].current_version_id == version.id
        assert loaded.case_versions[case.id][0].steps[0].action == "Open login"
        loaded_design = loaded.sessions[(project_id, design.id)]
        assert loaded_design.approved_stages == {"analysis"}
        assert loaded_design.review_gates[0].reviewer_id == gate.reviewer_id
        assert loaded_design.review_gates[0].comments == gate.comments
        assert loaded_design.review_gates[0].privileged_exception is True
        assert loaded.plans[(project_id, plan.id)].scope == (scope,)
        assert loaded.executions[(project_id, aggregate.id)].aggregate.attempts[version.id][0].attempt_no == 1
        assert loaded.reports[(project_id, aggregate.id)][0].revision == 1
        assert loaded.ingestions[(project_id, "ci", "run-1")].items[0].duration_ms == 20
        assert loaded.traceability_links[link.id].target.resource_id == case.id
        assert loaded.idempotency[(project_id, actor_id, "key-1")][2] == 201
        assert session.scalar(select(OutboxEventRow)) is not None
        assert "tp_unit_of_work_state" not in Base.metadata.tables


def test_frozen_plan_scope_and_terminal_attempt_are_sql_immutable() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    project_id = uuid4()
    actor_id = uuid4()
    environment = ManagedEnvironment(
        uuid4(), project_id, "QA", "test", "https://qa.example.test"
    )
    case_version_id = uuid4()
    original_scope = PlanScopeSnapshot(
        uuid4(), 1, "a" * 64, case_version_id, environment.id
    )
    plan = ManagedPlan(
        uuid4(), project_id, "PLAN-IMMUTABLE", actor_id, "ready",
        (original_scope,), "b" * 64, 2,
    )
    aggregate = Execution(
        uuid4(), project_id, plan.id, environment.id, actor_id
    )
    aggregate.start((case_version_id,))
    attempt = aggregate.attempts[case_version_id][0]
    attempt.transition("running")
    attempt.transition("passed", "original result")

    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        uow.environments[(project_id, environment.id)] = environment
        uow.plans[(project_id, plan.id)] = plan
        uow.executions[(project_id, aggregate.id)] = ManagedExecution(aggregate, 1)
        uow.commit()

    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        loaded_plan = uow.plans[(project_id, plan.id)]
        loaded_plan.scope = (
            PlanScopeSnapshot(
                original_scope.requirement_ref,
                2,
                "c" * 64,
                case_version_id,
                environment.id,
            ),
        )
        with pytest.raises(DomainError, match="immutable"):
            uow.commit()

    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        loaded_attempt = uow.executions[(project_id, aggregate.id)].aggregate.attempts[
            case_version_id
        ][0]
        loaded_attempt.status = "failed"
        loaded_attempt.actual_result = "overwritten"
        with pytest.raises(DomainError, match="cannot be overwritten"):
            uow.commit()


def test_http_idempotency_replays_before_domain_mutation() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    uow = SqlAlchemyUnitOfWork(Session(engine))
    client = create_app(uow).test_client()
    headers = {
        "X-Actor-Id": str(actor_id),
        "Idempotency-Key": "environment-key",
    }
    payload = {
        "name": "QA",
        "classification": "test",
        "base_url": "https://qa.example.test",
    }

    first = client.post(
        f"/api/v1/projects/{project_id}/test-environments",
        json=payload,
        headers=headers,
    )
    replay = client.post(
        f"/api/v1/projects/{project_id}/test-environments",
        json=payload,
        headers=headers,
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json == first.json
    assert len(uow.environments) == 1
    assert uow.commits == 1


def test_folder_http_idempotency_survives_sql_uow_restart() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    headers = {
        "X-Actor-Id": str(actor_id),
        "Idempotency-Key": "folder-key",
    }
    payload = {"name": "Regression"}

    first_uow = SqlAlchemyUnitOfWork(Session(engine))
    first = create_app(first_uow).test_client().post(
        f"/api/v1/projects/{project_id}/test-folders",
        json=payload,
        headers=headers,
    )
    restarted_uow = SqlAlchemyUnitOfWork(Session(engine))
    replay = create_app(restarted_uow).test_client().post(
        f"/api/v1/projects/{project_id}/test-folders",
        json=payload,
        headers=headers,
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json == first.json
    assert len(restarted_uow.folders) == 1


def test_config_fails_closed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "container")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Config.from_env()
