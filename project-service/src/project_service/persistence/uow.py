from types import TracebackType
from typing import Protocol, Self

from sqlalchemy.orm import Session

from project_service.collaboration.repository import CollaborationRepository
from project_service.database import Database
from project_service.idempotency.repository import IdempotencyRepository
from project_service.persistence.idempotency import SqlAlchemyIdempotencyRepository
from project_service.persistence.repositories import (
    SqlAlchemyAuditRepository,
    SqlAlchemyCollaborationRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyTaskRepository,
)
from project_service.projects.repository import ProjectRepository
from project_service.tasks.repository import TaskRepository


class UnitOfWork(Protocol):
    projects: ProjectRepository
    collaboration: CollaborationRepository
    tasks: TaskRepository
    idempotency: IdempotencyRepository
    audit: object
    outbox: object

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...
    def flush(self) -> None: ...
    def commit(self) -> None: ...


class SqlAlchemyUnitOfWork:
    """Transaction boundary with all collaboration repositories."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._session: Session | None = None

    def __enter__(self) -> Self:
        self._session = self._database.sessions()
        self.projects = SqlAlchemyProjectRepository(self._session)
        self.collaboration = SqlAlchemyCollaborationRepository(self._session)
        self.tasks = SqlAlchemyTaskRepository(self._session)
        self.idempotency = SqlAlchemyIdempotencyRepository(self._session)
        self.audit = SqlAlchemyAuditRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        return self

    def flush(self) -> None:
        """Flush pending changes while retaining the active transaction."""
        if self._session is None:
            raise RuntimeError("Unit of work is not active")
        self._session.flush()

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work is not active")
        self._session.commit()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is not None:
            if exc_type is not None or self._session.in_transaction():
                self._session.rollback()
            self._session.close()


class SqlAlchemyUnitOfWorkFactory:
    def __init__(self, database: Database) -> None:
        self._database = database

    def __call__(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._database)
