"""SQLAlchemy persistence for the audit service private database."""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from audit_service.records.models import AuditRecord


class Base(DeclarativeBase):
    """Declarative metadata root for the audit private database."""


class AuditRecordRow(Base):
    """Append-only persisted audit fact."""

    __tablename__ = "audit_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Validated audit database configuration."""

    environment: str = "development"
    database_url: str = ""

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        """Load settings and fail closed outside explicit test mode."""
        value = cls(
            environment=os.getenv("APP_ENV", "development").strip().lower(),
            database_url=os.getenv("DATABASE_URL", "").strip(),
        )
        if not value.database_url and value.environment != "test":
            raise RuntimeError("DATABASE_URL is required")
        return value


class SqlAlchemyAuditRepository:
    """Append-only SQL audit repository bound to one transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, record: AuditRecord) -> AuditRecord:
        """Append a fact or replay the existing fact for the same event id."""
        existing = self.session.scalar(
            select(AuditRecordRow).where(AuditRecordRow.event_id == record.event_id)
        )
        if existing is not None:
            return self._to_domain(existing)
        self.session.add(
            AuditRecordRow(
                id=record.id,
                event_id=record.event_id,
                occurred_at=record.occurred_at,
                ingested_at=record.ingested_at,
                trace_id=record.trace_id,
                actor_id=record.actor_id,
                actor_type=record.actor_type,
                project_id=record.project_id,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                action=record.action,
                result=record.result,
                source=record.source,
                metadata_json=dict(record.metadata),
                classification=record.classification,
            )
        )
        self.session.flush()
        return record

    def list(self) -> list[AuditRecord]:
        """Return facts in stable reverse chronological order."""
        rows = self.session.scalars(
            select(AuditRecordRow).order_by(
                AuditRecordRow.occurred_at.desc(), AuditRecordRow.id.desc()
            )
        )
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: AuditRecordRow) -> AuditRecord:
        return AuditRecord(
            id=row.id,
            event_id=row.event_id,
            occurred_at=row.occurred_at,
            ingested_at=row.ingested_at,
            trace_id=row.trace_id,
            actor_id=row.actor_id,
            actor_type=row.actor_type,
            project_id=row.project_id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            action=row.action,
            result=row.result,
            source=row.source,
            metadata=dict(row.metadata_json),
            classification=row.classification,
        )


class SqlAlchemyRuntime:
    """Own the audit engine and request-scoped sessions."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        self.engine: Engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        """Create a transaction-scoped session."""
        return self.sessions()

    def ready(self) -> None:
        """Raise when the private database cannot serve queries."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
