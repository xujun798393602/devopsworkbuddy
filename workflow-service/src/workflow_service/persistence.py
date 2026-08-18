"""PostgreSQL repository and transaction runtime for workflow-service."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    scoped_session,
    sessionmaker,
)

from workflow_service.workflows.models import (
    TASK_DEFINITION,
    WorkflowInstance,
    WorkflowTemplateVersion,
    WorkflowTransition,
)
from workflow_service.workflows.repository import (
    PORTAL_PENDING_STATES,
    PortalApprovalSnapshot,
)


class Base(DeclarativeBase):
    """Declarative metadata root for the workflow private database."""


class WorkflowTemplateVersionRow(Base):
    """Immutable workflow template version row."""

    __tablename__ = "workflow_template_versions"
    __table_args__ = (UniqueConstraint("template_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class WorkflowInstanceRow(Base):
    """Current workflow aggregate state row."""

    __tablename__ = "workflow_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    business_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    business_object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_state: Mapped[str] = mapped_column(String(64), nullable=False)
    started_by: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkflowTransitionRow(Base):
    """Append-only transition history row."""

    __tablename__ = "workflow_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    from_state: Mapped[str] = mapped_column(String(64), nullable=False)
    to_state: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowCommandRow(Base):
    """Durable idempotency record scoped by actor and key."""

    __tablename__ = "workflow_commands"

    actor_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    result_instance_id: Mapped[str] = mapped_column(String(36), nullable=False)


class WorkflowOutboxRow(Base):
    """Transactional outbox row."""

    __tablename__ = "workflow_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


class SqlAlchemyWorkflowRepository:
    """SQLAlchemy implementation of the workflow repository contract."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.templates: dict[tuple[str, int], WorkflowTemplateVersion] = {}
        self.instances: dict[str, WorkflowInstance] = {}
        self.commands: dict[tuple[str, str], tuple[str, object]] = {}
        self.outbox: list[dict[str, object]] = []
        self._seed_builtin()

    def _seed_builtin(self) -> None:
        if self.template("system.task-lifecycle", 1) is not None:
            return
        template = WorkflowTemplateVersion(
            "system.task-lifecycle",
            1,
            "Task lifecycle",
            TASK_DEFINITION,
        )
        template.publish()
        self.save_template(template)

    def template(self, key: str, version: int) -> WorkflowTemplateVersion | None:
        row = self.session.scalar(
            select(WorkflowTemplateVersionRow).where(
                WorkflowTemplateVersionRow.template_key == key,
                WorkflowTemplateVersionRow.version_no == version,
            )
        )
        if row is None:
            return None
        return WorkflowTemplateVersion(
            row.template_key,
            row.version_no,
            row.name,
            row.definition_json,
            row.status,
        )

    def instance(self, instance_id: str) -> WorkflowInstance | None:
        row = self.session.get(WorkflowInstanceRow, instance_id)
        if row is None:
            return None
        history_rows = self.session.scalars(
            select(WorkflowTransitionRow)
            .where(WorkflowTransitionRow.instance_id == instance_id)
            .order_by(WorkflowTransitionRow.occurred_at, WorkflowTransitionRow.id)
        ).all()
        return WorkflowInstance(
            row.id,
            row.project_id,
            row.business_object_type,
            row.business_object_id,
            row.template_key,
            row.template_version,
            row.current_state,
            row.started_by,
            row.status,
            row.version,
            [
                WorkflowTransition(
                    item.id,
                    item.from_state,
                    item.to_state,
                    item.action,
                    item.actor_id,
                    item.reason,
                    item.occurred_at,
                )
                for item in history_rows
            ],
        )

    def save_template(self, template: WorkflowTemplateVersion) -> None:
        row = self.session.scalar(
            select(WorkflowTemplateVersionRow).where(
                WorkflowTemplateVersionRow.template_key == template.template_key,
                WorkflowTemplateVersionRow.version_no == template.version_no,
            )
        )
        if row is None:
            row = WorkflowTemplateVersionRow(
                id=str(uuid4()),
                template_key=template.template_key,
                version_no=template.version_no,
                name=template.name,
                status=template.status,
                definition_json=template.definition,
            )
            self.session.add(row)
            return
        row.name = template.name
        row.status = template.status
        row.definition_json = template.definition

    def save_instance(self, instance: WorkflowInstance) -> None:
        row = self.session.get(WorkflowInstanceRow, instance.id)
        if row is None:
            row = WorkflowInstanceRow(
                id=instance.id,
                project_id=instance.project_id,
                business_object_type=instance.business_object_type,
                business_object_id=instance.business_object_id,
                template_key=instance.template_key,
                template_version=instance.template_version,
                current_state=instance.current_state,
                started_by=instance.started_by,
                status=instance.status,
                version=instance.version,
            )
            self.session.add(row)
        else:
            row.current_state = instance.current_state
            row.status = instance.status
            row.version = instance.version
        known_ids = set(
            self.session.scalars(
                select(WorkflowTransitionRow.id).where(
                    WorkflowTransitionRow.instance_id == instance.id
                )
            ).all()
        )
        for transition in instance.history:
            if transition.id not in known_ids:
                self.session.add(
                    WorkflowTransitionRow(instance_id=instance.id, **asdict(transition))
                )

    def command(self, actor_id: str, key: str) -> tuple[str, object] | None:
        row = self.session.get(WorkflowCommandRow, (actor_id, key))
        if row is None:
            return None
        instance = self.instance(row.result_instance_id)
        return None if instance is None else (row.signature, instance)

    def save_command(
        self,
        actor_id: str,
        key: str,
        signature: str,
        result: object,
    ) -> None:
        if not isinstance(result, WorkflowInstance):
            raise TypeError("workflow command result must be a WorkflowInstance")
        self.session.add(
            WorkflowCommandRow(
                actor_id=actor_id,
                idempotency_key=key,
                signature=signature,
                result_instance_id=result.id,
            )
        )

    def append_outbox(self, event: dict[str, object]) -> None:
        self.session.add(
            WorkflowOutboxRow(
                id=str(uuid4()),
                event_type=str(event["event_type"]),
                payload=event,
                status="pending",
            )
        )

    def list_instances(self, project_id: str) -> list[WorkflowInstance]:
        instance_ids = self.session.scalars(
            select(WorkflowInstanceRow.id).where(
                WorkflowInstanceRow.project_id == project_id
            )
        ).all()
        return [
            instance
            for instance_id in instance_ids
            if (instance := self.instance(instance_id)) is not None
        ]


class SqlAlchemyPortalRepository:
    """PostgreSQL pending-approvals projection using batch statements."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def pending_approvals(
        self, project_ids: tuple[str, ...], cross_project: bool
    ) -> list[PortalApprovalSnapshot]:
        if not project_ids and not cross_project:
            return []
        stmt = select(WorkflowInstanceRow).where(
            WorkflowInstanceRow.current_state.in_(tuple(PORTAL_PENDING_STATES))
        )
        if project_ids:
            stmt = stmt.where(WorkflowInstanceRow.project_id.in_(tuple(project_ids)))
        rows = self.session.scalars(stmt).all()
        if not rows:
            return []
        instance_ids = tuple(row.id for row in rows)
        first_transitions = self.session.execute(
            select(
                WorkflowTransitionRow.instance_id,
                func.min(WorkflowTransitionRow.occurred_at),
            )
            .where(WorkflowTransitionRow.instance_id.in_(instance_ids))
            .group_by(WorkflowTransitionRow.instance_id)
        ).all()
        started_map = {instance_id: occurred_at for instance_id, occurred_at in first_transitions}
        snapshots = [
            PortalApprovalSnapshot(
                row.id,
                row.project_id,
                row.business_object_type,
                row.business_object_id,
                row.current_state,
                started_map.get(row.id).isoformat() if started_map.get(row.id) else None,
            )
            for row in rows
        ]
        snapshots.sort(key=lambda snapshot: (snapshot.started_at or "", snapshot.id))
        return snapshots


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Database settings with production fail-closed validation."""

    environment: str = "development"
    database_url: str = ""

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        """Load settings and reject missing production database configuration."""
        settings = cls(
            os.getenv("APP_ENV", "development").strip().lower(),
            os.getenv("DATABASE_URL", "").strip(),
        )
        if settings.environment in {"production", "container"} and not settings.database_url:
            raise RuntimeError("DATABASE_URL is required in production")
        return settings


class SqlAlchemyRuntime:
    """Request-scoped SQLAlchemy sessions and readiness checks."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        self.engine: Engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = scoped_session(
            sessionmaker(self.engine, expire_on_commit=False)
        )

    def repository(self) -> SqlAlchemyWorkflowRepository:
        """Create a repository bound to the current request session."""
        return SqlAlchemyWorkflowRepository(self.sessions)

    def portal_repository(self) -> SqlAlchemyPortalRepository:
        """Create the portal read projection bound to the current session."""
        return SqlAlchemyPortalRepository(self.sessions)

    def commit(self) -> None:
        """Commit the current request transaction."""
        self.sessions.commit()

    def rollback(self) -> None:
        """Rollback the current request transaction."""
        self.sessions.rollback()

    def remove(self) -> None:
        """Close and remove the current request session."""
        self.sessions.remove()

    def ready(self) -> None:
        """Raise when the private database is unavailable."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
