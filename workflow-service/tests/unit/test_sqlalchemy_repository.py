"""SQLAlchemy workflow repository and production configuration tests."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from workflow_service.integrations.project_authorization import ControlledAuthorizer
from workflow_service.persistence import (
    Base,
    DatabaseSettings,
    SqlAlchemyWorkflowRepository,
    WorkflowCommandRow,
    WorkflowInstanceRow,
    WorkflowOutboxRow,
)
from workflow_service.workflows.service import WorkflowService


def test_repository_persists_instance_command_and_outbox() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    grants = {("user-1", "project-1", "workflow.start")}
    with Session(engine, expire_on_commit=False) as session:
        repository = SqlAlchemyWorkflowRepository(session)
        service = WorkflowService(repository, ControlledAuthorizer(grants))
        instance = service.start(
            {
                "project_id": "project-1",
                "business_object_type": "task",
                "business_object_id": "task-1",
            },
            "user-1",
            "command-1",
        )
        session.commit()

    with Session(engine) as session:
        assert session.get(WorkflowInstanceRow, instance.id) is not None
        assert session.get(WorkflowCommandRow, ("user-1", "command-1")) is not None
        assert session.scalar(select(WorkflowOutboxRow)) is not None
        replay = SqlAlchemyWorkflowRepository(session).command("user-1", "command-1")
        assert replay is not None
        assert replay[1].id == instance.id


def test_production_settings_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        DatabaseSettings.from_env()
