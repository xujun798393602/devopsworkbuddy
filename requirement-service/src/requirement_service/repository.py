"""Requirement repositories and transaction boundaries."""
from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from requirement_service.domain import (
    Baseline,
    ChangeRequest,
    Requirement,
    RequirementRevision,
    RequirementStatus,
    RequirementType,
    ReviewRound,
)
from requirement_service.persistence import (
    BaselineRow,
    ChangeRequestRow,
    IdempotencyRow,
    OutboxRow,
    RequirementRevisionRow,
    RequirementRow,
    ReviewRoundRow,
)


def requirement_from_row(row: RequirementRow) -> Requirement:
    """Rehydrate the requirement aggregate from its persisted row."""
    return Requirement(
        UUID(row.id),
        UUID(row.project_id),
        row.business_no,
        row.title,
        RequirementType(row.type),
        UUID(row.owner_id),
        UUID(row.release_version_id),
        row.description,
        UUID(row.parent_id) if row.parent_id else None,
        row.priority,
        RequirementStatus(row.status),
        list(row.acceptance_criteria),
        row.current_revision,
        row.version,
        row.baseline_status,
    )


def _portal_scope(project_ids: tuple[str, ...] | list[str]) -> set[str]:
    """Normalise the requested project scope to comparable string identifiers."""
    return {str(value) for value in project_ids}


class RequirementMapping(MutableMapping[tuple[UUID, UUID], Requirement]):
    """Project-scoped mapping backed by one SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __getitem__(self, key: tuple[UUID, UUID]) -> Requirement:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: tuple[UUID, UUID], value: Requirement) -> None:
        project_id, requirement_id = key
        if value.project_id != project_id or value.id != requirement_id:
            raise ValueError("requirement repository key does not match aggregate")
        row = self.session.get(RequirementRow, str(requirement_id))
        values = {
            "project_id": str(value.project_id),
            "business_no": value.business_no,
            "title": value.title,
            "type": value.type.value,
            "owner_id": str(value.owner_id),
            "release_version_id": str(value.release_version_id),
            "description": value.description,
            "parent_id": str(value.parent_id) if value.parent_id else None,
            "priority": value.priority,
            "status": value.status.value,
            "acceptance_criteria": value.acceptance_criteria,
            "current_revision": value.current_revision,
            "version": value.version,
            "baseline_status": value.baseline_status,
        }
        if row is None:
            self.session.add(RequirementRow(id=str(value.id), **values))
        else:
            for name, item in values.items():
                setattr(row, name, item)

    def __delitem__(self, key: tuple[UUID, UUID]) -> None:
        value = self[key]
        row = self.session.get(RequirementRow, str(value.id))
        if row is not None:
            self.session.delete(row)

    def __iter__(self) -> Iterator[tuple[UUID, UUID]]:
        rows = self.session.execute(
            select(RequirementRow.project_id, RequirementRow.id)
        ).all()
        return iter((UUID(project_id), UUID(requirement_id)) for project_id, requirement_id in rows)

    def __len__(self) -> int:
        return len(self.session.scalars(select(RequirementRow.id)).all())

    def get(
        self,
        key: tuple[UUID, UUID],
        default: Requirement | None = None,
    ) -> Requirement | None:
        project_id, requirement_id = key
        row = self.session.scalar(
            select(RequirementRow).where(
                RequirementRow.id == str(requirement_id),
                RequirementRow.project_id == str(project_id),
            )
        )
        if row is None:
            return default
        return requirement_from_row(row)


class RevisionMapping(MutableMapping[UUID, list[RequirementRevision]]):
    """Append-only revision collection backed by SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __getitem__(self, key: UUID) -> list[RequirementRevision]:
        rows = self.session.scalars(
            select(RequirementRevisionRow)
            .where(RequirementRevisionRow.requirement_id == str(key))
            .order_by(RequirementRevisionRow.revision_no)
        ).all()
        if not rows:
            raise KeyError(key)
        return [
            RequirementRevision(
                UUID(row.id),
                UUID(row.requirement_id),
                row.revision_no,
                row.content_hash,
                row.snapshot,
            )
            for row in rows
        ]

    def __setitem__(self, key: UUID, values: list[RequirementRevision]) -> None:
        known_ids = set(
            self.session.scalars(
                select(RequirementRevisionRow.id).where(
                    RequirementRevisionRow.requirement_id == str(key)
                )
            ).all()
        )
        for value in values:
            if str(value.id) not in known_ids:
                self.session.add(
                    RequirementRevisionRow(
                        id=str(value.id),
                        requirement_id=str(value.requirement_id),
                        revision_no=value.revision_no,
                        content_hash=value.content_hash,
                        snapshot=value.snapshot,
                    )
                )

    def __delitem__(self, key: UUID) -> None:
        raise TypeError("requirement revisions are append-only")

    def __iter__(self) -> Iterator[UUID]:
        values = self.session.scalars(
            select(RequirementRevisionRow.requirement_id).distinct()
        ).all()
        return iter(UUID(value) for value in values)

    def __len__(self) -> int:
        return len(list(iter(self)))


class OutboxList(list[dict[str, Any]]):
    """List-compatible transactional outbox writer."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session

    def append(self, event: dict[str, Any]) -> None:
        self.session.add(
            OutboxRow(event_type=str(event["event_type"]), payload=event, status="pending")
        )
        super().append(event)


@dataclass(slots=True)
class MemoryUnitOfWork:
    """Atomic in-memory adapter used only when explicitly selected."""

    requirements: dict[tuple[UUID, UUID], Requirement] = field(default_factory=dict)
    revisions: dict[UUID, list[RequirementRevision]] = field(default_factory=dict)
    outbox: list[dict[str, Any]] = field(default_factory=list)
    reviews: dict[UUID, ReviewRound] = field(default_factory=dict)
    baselines: dict[tuple[UUID, UUID], Baseline] = field(default_factory=dict)
    change_requests: dict[tuple[UUID, UUID], ChangeRequest] = field(default_factory=dict)
    idempotency: dict[tuple[str, str, str], tuple[str, dict[str, Any], int]] = field(
        default_factory=dict
    )
    commits: int = 0

    def commit(self) -> None:
        """Record a successful transaction boundary."""
        self.commits += 1

    def rollback(self) -> None:
        """Keep the adapter API aligned with production."""

    def portal_requirements(
        self, project_ids: tuple[str, ...], cross_project: bool
    ) -> list[Requirement]:
        """Return every requirement inside the requested portal scope."""
        scope = _portal_scope(project_ids)
        if not cross_project and not scope:
            return []
        return [
            value
            for (project_id, _), value in self.requirements.items()
            if cross_project or str(project_id) in scope
        ]

    def portal_active_baseline_total(
        self, project_ids: tuple[str, ...], cross_project: bool
    ) -> int:
        """Count active baselines inside the requested portal scope."""
        scope = _portal_scope(project_ids)
        if not cross_project and not scope:
            return 0
        return sum(
            1
            for (project_id, _), value in self.baselines.items()
            if (cross_project or str(project_id) in scope) and value.status == "active"
        )

    def get_idempotency(
        self, project_id: str, actor_id: str, key: str
    ) -> tuple[str, dict[str, Any], int] | None:
        return self.idempotency.get((project_id, actor_id, key))

    def save_idempotency(
        self,
        project_id: str,
        actor_id: str,
        key: str,
        request_hash: str,
        response_body: dict[str, Any],
        response_status: int,
    ) -> None:
        self.idempotency[(project_id, actor_id, key)] = (
            request_hash,
            response_body,
            response_status,
        )

    def list_requirements(
        self, project_id: UUID, offset: int, limit: int
    ) -> list[Requirement]:
        """Return one deterministic page of project requirements (cursor-ready).

        Ordered by ``(business_no, id)`` so an opaque offset cursor stays stable
        across pages; the HTTP adapter requests ``limit + 1`` rows to learn
        whether another page exists.
        """
        values = [
            value
            for (scope, _), value in self.requirements.items()
            if scope == project_id
        ]
        values.sort(key=lambda item: (item.business_no, str(item.id)))
        return values[offset : offset + limit]


class SqlAlchemyUnitOfWork:
    """Request-scoped SQLAlchemy unit of work."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.requirements = RequirementMapping(session)
        self.revisions = RevisionMapping(session)
        self.outbox = OutboxList(session)
        self.reviews = self._load_reviews()
        self.baselines = self._load_baselines()
        self.change_requests = self._load_change_requests()

    def _load_reviews(self) -> dict[UUID, ReviewRound]:
        return {
            UUID(row.id): ReviewRound(
                UUID(row.id),
                row.round_no,
                UUID(row.revision_id),
                UUID(row.submitted_by),
                tuple(UUID(value) for value in row.reviewer_ids),
                row.status,
                list(row.decisions),
            )
            for row in self.session.scalars(select(ReviewRoundRow))
        }

    def _load_baselines(self) -> dict[tuple[UUID, UUID], Baseline]:
        result: dict[tuple[UUID, UUID], Baseline] = {}
        for row in self.session.scalars(select(BaselineRow)):
            value = Baseline(
                UUID(row.id),
                UUID(row.project_id),
                row.baseline_no,
                UUID(row.release_version_id),
                tuple((UUID(item[0]), item[1]) for item in row.revision_refs),
                row.status,
                row.version,
            )
            result[(value.project_id, value.id)] = value
        return result

    def _load_change_requests(self) -> dict[tuple[UUID, UUID], ChangeRequest]:
        result: dict[tuple[UUID, UUID], ChangeRequest] = {}
        for row in self.session.scalars(select(ChangeRequestRow)):
            value = ChangeRequest(
                UUID(row.id),
                UUID(row.requirement_id),
                UUID(row.base_revision_id),
                dict(row.proposed_patch),
                row.status,
                row.version,
            )
            result[(UUID(row.project_id), value.id)] = value
        return result

    def commit(self) -> None:
        for value in self.reviews.values():
            values = {
                "requirement_id": str(self.session.scalar(
                    select(RequirementRevisionRow.requirement_id).where(
                        RequirementRevisionRow.id == str(value.revision_id)
                    )
                )),
                "round_no": value.round_no,
                "revision_id": str(value.revision_id),
                "submitted_by": str(value.submitted_by),
                "reviewer_ids": [str(item) for item in value.reviewer_ids],
                "status": value.status,
                "decisions": list(value.decisions),
            }
            row = self.session.get(ReviewRoundRow, str(value.id))
            if row is None:
                self.session.add(ReviewRoundRow(id=str(value.id), **values))
            else:
                row.status = value.status
                row.decisions = values["decisions"]
        for (project_id, _), value in self.baselines.items():
            row = self.session.get(BaselineRow, str(value.id))
            values = {
                "project_id": str(project_id),
                "baseline_no": value.baseline_no,
                "release_version_id": str(value.release_version_id),
                "revision_refs": [[str(item[0]), item[1]] for item in value.revision_refs],
                "status": value.status,
                "version": value.version,
            }
            if row is None:
                self.session.add(BaselineRow(id=str(value.id), **values))
            else:
                for name, item in values.items():
                    setattr(row, name, item)
        for (project_id, _), value in self.change_requests.items():
            row = self.session.get(ChangeRequestRow, str(value.id))
            values = {
                "project_id": str(project_id),
                "requirement_id": str(value.requirement_id),
                "base_revision_id": str(value.base_revision_id),
                "proposed_patch": dict(value.proposed_patch),
                "status": value.status,
                "version": value.version,
            }
            if row is None:
                self.session.add(ChangeRequestRow(id=str(value.id), **values))
            else:
                for name, item in values.items():
                    setattr(row, name, item)
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def portal_requirements(
        self, project_ids: tuple[str, ...], cross_project: bool
    ) -> list[Requirement]:
        """Return every requirement inside the portal scope with one statement."""
        scope = sorted(_portal_scope(project_ids))
        if not cross_project and not scope:
            return []
        statement = select(RequirementRow)
        if not cross_project:
            statement = statement.where(RequirementRow.project_id.in_(scope))
        statement = statement.order_by(RequirementRow.project_id, RequirementRow.business_no)
        return [requirement_from_row(row) for row in self.session.scalars(statement)]

    def portal_active_baseline_total(
        self, project_ids: tuple[str, ...], cross_project: bool
    ) -> int:
        """Count active baselines inside the portal scope with one statement."""
        scope = sorted(_portal_scope(project_ids))
        if not cross_project and not scope:
            return 0
        statement = select(func.count(BaselineRow.id)).where(BaselineRow.status == "active")
        if not cross_project:
            statement = statement.where(BaselineRow.project_id.in_(scope))
        return int(self.session.scalar(statement) or 0)

    def get_idempotency(
        self, project_id: str, actor_id: str, key: str
    ) -> tuple[str, dict[str, Any], int] | None:
        row = self.session.get(IdempotencyRow, (project_id, actor_id, key))
        if row is None:
            return None
        return row.request_hash, row.response_body, row.response_status

    def save_idempotency(
        self,
        project_id: str,
        actor_id: str,
        key: str,
        request_hash: str,
        response_body: dict[str, Any],
        response_status: int,
    ) -> None:
        self.session.add(
            IdempotencyRow(
                project_id=project_id,
                actor_id=actor_id,
                idempotency_key=key,
                request_hash=request_hash,
                response_body=response_body,
                response_status=response_status,
            )
        )

    def list_requirements(
        self, project_id: UUID, offset: int, limit: int
    ) -> list[Requirement]:
        """Return one deterministic page of project requirements (cursor-ready)."""
        statement = (
            select(RequirementRow)
            .where(RequirementRow.project_id == str(project_id))
            .order_by(RequirementRow.business_no, RequirementRow.id)
            .offset(offset)
            .limit(limit)
        )
        return [requirement_from_row(row) for row in self.session.scalars(statement)]


class SqlAlchemyRuntime:
    """Own the engine and request-scoped sessions for requirement-service."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = scoped_session(sessionmaker(engine, expire_on_commit=False))

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.sessions)

    def ready(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def remove(self) -> None:
        self.sessions.remove()


class AllowAllAuthorizer:
    """Explicit test adapter; production should replace it with authorization HTTP."""

    def check(self, actor_id: UUID, project_id: UUID, action: str) -> bool:
        return bool(actor_id and project_id and action)
