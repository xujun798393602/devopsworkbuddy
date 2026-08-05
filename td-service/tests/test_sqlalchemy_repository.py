"""TD SQLAlchemy repository and production configuration tests."""
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from td_service.config import Config
from td_service.domain import Defect, FixEvidence
from td_service.persistence import (
    Base,
    DefectDuplicateRow,
    DefectHistoryRow,
    IdempotencyRow,
    OutboxRow,
    assert_duplicate_edge_is_acyclic,
)
from td_service.repository import SqlAlchemyUnitOfWork


def _defect() -> Defect:
    return Defect(
        id=uuid4(),
        project_id=uuid4(),
        business_no="TD-900",
        title="Checkout fails",
        description="Payment gateway rejects valid cards",
        severity="major",
        priority="p1",
        defect_type="functional",
        reporter_id=uuid4(),
        expected_result="Payment completes",
        actual_result="Gateway error",
        reproduction_steps=("Open checkout", "Pay"),
    )


def test_sqlalchemy_uow_round_trips_aggregate_outbox_and_idempotency() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    defect = _defect()
    actor_id = uuid4()
    assignee_id = uuid4()
    defect.transition("assign", actor_id, assignee_id=assignee_id)
    defect.transition("start", assignee_id)
    defect.transition(
        "mark_fixed",
        assignee_id,
        fix_version_id=uuid4(),
        fix_evidence=FixEvidence("commit", "abc123", "Add null guard"),
    )
    body = {"data": {"id": str(defect.id)}}
    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        uow.defects[(defect.project_id, defect.id)] = defect
        uow.idempotency[(defect.project_id, actor_id, "create-1")] = ("a" * 64, body, 201)
        uow.outbox.append(
            {
                "event_type": "Defect.Fixed",
                "defect_id": str(defect.id),
                "project_id": str(defect.project_id),
            }
        )
        uow.commit()
    with Session(engine) as session:
        loaded = SqlAlchemyUnitOfWork(session)
        actual = loaded.defects[(defect.project_id, defect.id)]
        assert actual.status.value == "fixed"
        assert actual.fix_evidence == defect.fix_evidence
        assert len(actual.history) == 3
        assert session.scalar(select(OutboxRow)) is not None
        assert session.scalar(select(IdempotencyRow)) is not None


def test_sql_append_only_history_evidence_and_sla_policy_snapshot() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    defect = _defect()
    actor_id = uuid4()
    assignee_id = uuid4()
    defect.transition("assign", actor_id, assignee_id=assignee_id)
    defect.transition("start", assignee_id)
    defect.transition(
        "mark_fixed",
        assignee_id,
        fix_version_id=uuid4(),
        fix_evidence=FixEvidence("commit", "abc123", "Original evidence"),
    )
    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        uow.defects[(defect.project_id, defect.id)] = defect
        uow.commit()

    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        loaded = uow.defects[(defect.project_id, defect.id)]
        loaded.history[0]["reason"] = "tampered"
        with pytest.raises(ValueError, match="HISTORY_APPEND_ONLY"):
            uow.commit()

    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        loaded = uow.defects[(defect.project_id, defect.id)]
        loaded.fix_evidence[0] = FixEvidence("commit", "changed", "Tampered")
        with pytest.raises(ValueError, match="EVIDENCE_APPEND_ONLY"):
            uow.commit()

    with Session(engine) as session:
        uow = SqlAlchemyUnitOfWork(session)
        loaded = uow.defects[(defect.project_id, defect.id)]
        assert loaded.sla is not None
        loaded.sla.policy_version = "v2"
        with pytest.raises(ValueError, match="SLA_POLICY_SNAPSHOT_IMMUTABLE"):
            uow.commit()


def test_duplicate_guard_builds_recursive_project_scoped_cte_for_postgresql() -> None:
    statements: list[object] = []

    class ScalarSession:
        calls = 0

        def scalar(self, statement: object) -> object:
            statements.append(statement)
            self.calls += 1
            return uuid4() if self.calls == 1 else None

    assert_duplicate_edge_is_acyclic(
        ScalarSession(), uuid4(), uuid4(), uuid4()  # type: ignore[arg-type]
    )
    assert len(statements) == 2
    compiled = str(
        statements[1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "WITH RECURSIVE duplicate_chain" in compiled
    assert "defect_duplicates.project_id" in compiled
    assert "UNION ALL" in compiled


def test_persisted_history_rows_are_structurally_append_only() -> None:
    table = DefectHistoryRow.__table__
    assert tuple(column.name for column in table.primary_key.columns) == (
        "defect_id",
        "sequence_no",
    )
    assert DefectDuplicateRow.__table__.c.project_id.nullable is False


def test_config_fails_closed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Config.from_env()
