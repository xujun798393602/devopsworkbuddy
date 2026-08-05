"""SQL audit repository and production assembly tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from audit_service.app import create_app
from audit_service.persistence import (
    AuditRecordRow,
    Base,
    DatabaseSettings,
    SqlAlchemyAuditRepository,
)
from audit_service.records.models import AuditRecord
from audit_service.records.repository import InMemoryAuditRepository


def record() -> AuditRecord:
    """Build a complete immutable test fact."""
    now = datetime.now(UTC)
    return AuditRecord(
        "record-1",
        "event-1",
        now,
        now,
        "trace-1",
        "actor-1",
        "user",
        "project-1",
        "workflow",
        "workflow-1",
        "changed",
        "success",
        "test",
        {"safe": True},
        "internal",
    )


def test_sql_repository_persists_and_replays_event() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    expected = record()
    with Session(engine) as session:
        repository = SqlAlchemyAuditRepository(session)
        first = repository.append(expected)
        session.commit()
        replay = repository.append(record())
        assert replay.id == first.id
        assert session.query(AuditRecordRow).count() == 1
    with Session(engine) as session:
        loaded = SqlAlchemyAuditRepository(session).list()
        assert len(loaded) == 1
        assert loaded[0].event_id == expected.event_id
        assert loaded[0].metadata == expected.metadata


def test_production_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        DatabaseSettings.from_env()


def test_memory_adapter_requires_explicit_injection() -> None:
    app = create_app(InMemoryAuditRepository())
    assert app.test_client().get("/ready").get_json()["adapter"] == "memory"
