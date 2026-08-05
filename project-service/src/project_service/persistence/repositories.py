"""SQLAlchemy repository implementations."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, text, tuple_, update
from sqlalchemy.orm import Session

from project_service.collaboration.models import Iteration, ProjectMembership, ReleaseVersion, Role
from project_service.persistence.tables import (
    AuditRecordRow,
    IterationRow,
    OutboxEventRow,
    ProjectCounterRow,
    ProjectMembershipRow,
    ProjectRow,
    ReleaseVersionRow,
    TaskParticipantRow,
    TaskRow,
    WorklogRow,
)
from project_service.projects.models import Project
from project_service.shared.audit import AuditRecord, OutboxEvent
from project_service.shared.errors import ValidationError
from project_service.tasks.models import Task, Worklog


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


class SqlAlchemyProjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, project: Project) -> Project:
        self._session.add(
            ProjectRow(
                id=UUID(project.id),
                business_no=project.business_no,
                name=project.name,
                description=project.description,
                owner_id=project.owner_id,
                status=project.status,
                version=project.version,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )
        return project

    def get(self, project_id: str, *, for_update: bool = False) -> Project | None:
        resource_id = _uuid(project_id)
        if resource_id is None:
            return None
        statement = select(ProjectRow).where(ProjectRow.id == resource_id)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        return _project(row) if row else None

    def list_for_actor(self, actor_id: str) -> list[Project]:
        statement = (
            select(ProjectRow)
            .join(ProjectMembershipRow, ProjectMembershipRow.project_id == ProjectRow.id)
            .where(
                ProjectMembershipRow.user_id == actor_id, ProjectMembershipRow.status == "active"
            )
            .order_by(ProjectRow.created_at.desc(), ProjectRow.id)
        )
        return [_project(row) for row in self._session.scalars(statement)]

    def next_business_no(self) -> str:
        sequence = self._session.execute(
            text("SELECT nextval('project_business_no_seq')")
        ).scalar_one()
        return f"PRJ-{sequence:06d}"

    def save(self, project: Project, expected_version: int) -> bool:
        result = self._session.execute(
            update(ProjectRow)
            .where(ProjectRow.id == UUID(project.id), ProjectRow.version == expected_version)
            .values(
                owner_id=project.owner_id,
                status=project.status,
                version=project.version,
                updated_at=project.updated_at,
            )
        )
        return result.rowcount == 1


class SqlAlchemyCollaborationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active_membership(
        self, project_id: str, user_id: str, *, for_update: bool = False
    ) -> ProjectMembership | None:
        pid = _uuid(project_id)
        if pid is None:
            return None
        statement = select(ProjectMembershipRow).where(
            ProjectMembershipRow.project_id == pid,
            ProjectMembershipRow.user_id == user_id,
            ProjectMembershipRow.status == "active",
        )
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        return _membership(row) if row else None

    def get_membership(
        self, project_id: str, membership_id: str, *, for_update: bool = False
    ) -> ProjectMembership | None:
        pid, rid = _uuid(project_id), _uuid(membership_id)
        if pid is None or rid is None:
            return None
        statement = select(ProjectMembershipRow).where(
            ProjectMembershipRow.project_id == pid, ProjectMembershipRow.id == rid
        )
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        return _membership(row) if row else None

    def list_members(self, project_id: str) -> list[ProjectMembership]:
        pid = _uuid(project_id)
        if pid is None:
            return []
        return [
            _membership(row)
            for row in self._session.scalars(
                select(ProjectMembershipRow)
                .where(
                    ProjectMembershipRow.project_id == pid, ProjectMembershipRow.status == "active"
                )
                .order_by(ProjectMembershipRow.joined_at, ProjectMembershipRow.id)
            )
        ]

    def add_membership(self, membership: ProjectMembership) -> None:
        self._session.add(
            ProjectMembershipRow(
                id=UUID(membership.id),
                project_id=UUID(membership.project_id),
                user_id=membership.user_id,
                role=membership.role.value,
                status=membership.status,
                joined_at=membership.joined_at,
                joined_by=membership.joined_by,
                removed_at=membership.removed_at,
                removed_by=membership.removed_by,
                version=membership.version,
            )
        )

    def save_membership(self, membership: ProjectMembership, expected_version: int) -> bool:
        result = self._session.execute(
            update(ProjectMembershipRow)
            .where(
                ProjectMembershipRow.project_id == UUID(membership.project_id),
                ProjectMembershipRow.id == UUID(membership.id),
                ProjectMembershipRow.version == expected_version,
            )
            .values(
                role=membership.role.value,
                status=membership.status,
                removed_at=membership.removed_at,
                removed_by=membership.removed_by,
                version=membership.version,
            )
        )
        return result.rowcount == 1

    def transfer_owner_roles(
        self,
        project_id: str,
        current_id: str,
        target_id: str,
        current_version: int,
        target_version: int,
    ) -> bool:
        statement = text(
            """
            UPDATE project_memberships
            SET role = CASE WHEN id = :current_id THEN 'admin' ELSE 'owner' END,
                version = version + 1
            WHERE project_id = :project_id
              AND ((id = :current_id AND version = :current_version)
                   OR (id = :target_id AND version = :target_version))
            """
        )
        result = self._session.execute(
            statement,
            {
                "project_id": project_id,
                "current_id": current_id,
                "target_id": target_id,
                "current_version": current_version,
                "target_version": target_version,
            },
        )
        return result.rowcount == 2

    def get_version(
        self, project_id: str, resource_id: str, *, for_update: bool = False
    ) -> ReleaseVersion | None:
        return self._get_plan(ReleaseVersionRow, _version, project_id, resource_id, for_update)

    def list_versions(self, project_id: str) -> list[ReleaseVersion]:
        return self._list_plan(ReleaseVersionRow, _version, project_id)

    def add_version(self, item: ReleaseVersion) -> None:
        self._session.add(ReleaseVersionRow(**_version_values(item)))

    def save_version(self, item: ReleaseVersion, expected_version: int) -> bool:
        return self._save_plan(ReleaseVersionRow, item, expected_version, _version_values(item))

    def get_iteration(
        self, project_id: str, resource_id: str, *, for_update: bool = False
    ) -> Iteration | None:
        return self._get_plan(IterationRow, _iteration, project_id, resource_id, for_update)

    def list_iterations(self, project_id: str) -> list[Iteration]:
        return self._list_plan(IterationRow, _iteration, project_id)

    def add_iteration(self, item: Iteration) -> None:
        self._session.add(IterationRow(**_iteration_values(item)))

    def save_iteration(self, item: Iteration, expected_version: int) -> bool:
        return self._save_plan(IterationRow, item, expected_version, _iteration_values(item))

    def next_counter(self, project_id: str, counter_type: str) -> int:
        pid = UUID(project_id)
        row = self._session.scalar(
            select(ProjectCounterRow)
            .where(
                ProjectCounterRow.project_id == pid, ProjectCounterRow.counter_type == counter_type
            )
            .with_for_update()
        )
        if row is None:
            row = ProjectCounterRow(project_id=pid, counter_type=counter_type, next_value=2)
            self._session.add(row)
            return 1
        value = row.next_value
        row.next_value += 1
        return value

    def _get_plan(self, table, converter, project_id: str, resource_id: str, for_update: bool):
        pid, rid = _uuid(project_id), _uuid(resource_id)
        if pid is None or rid is None:
            return None
        statement = select(table).where(table.project_id == pid, table.id == rid)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        return converter(row) if row else None

    def _list_plan(self, table, converter, project_id: str):
        pid = _uuid(project_id)
        if pid is None:
            return []
        return [
            converter(row)
            for row in self._session.scalars(
                select(table).where(table.project_id == pid).order_by(table.created_at, table.id)
            )
        ]

    def _save_plan(self, table, item, expected: int, values: dict) -> bool:
        result = self._session.execute(
            update(table)
            .where(
                table.project_id == UUID(item.project_id),
                table.id == UUID(item.id),
                table.version == expected,
            )
            .values(**values)
        )
        return result.rowcount == 1


class SqlAlchemyTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, project_id: str, resource_id: str, *, for_update: bool = False) -> Task | None:
        pid, rid = _uuid(project_id), _uuid(resource_id)
        if pid is None or rid is None:
            return None
        statement = select(TaskRow).where(TaskRow.project_id == pid, TaskRow.id == rid)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        return self._to_task(row) if row else None

    def list(
        self,
        project_id: str,
        limit: int = 50,
        after: tuple[str, str] | None = None,
    ) -> list[Task]:
        pid = _uuid(project_id)
        if pid is None:
            return []
        statement = select(TaskRow).where(TaskRow.project_id == pid)
        if after is not None:
            try:
                created_at = datetime.fromisoformat(after[0].replace("Z", "+00:00"))
                resource_id = UUID(after[1])
            except (ValueError, TypeError) as error:
                raise ValidationError("cursor is invalid") from error
            statement = statement.where(
                tuple_(TaskRow.created_at, TaskRow.id) > tuple_(created_at, resource_id)
            )
        rows = self._session.scalars(
            statement.order_by(TaskRow.created_at, TaskRow.id).limit(limit)
        )
        return [self._to_task(row) for row in rows]

    def has_open_tasks(self, project_id: str, scope_type: str, scope_id: str) -> bool:
        pid, sid = _uuid(project_id), _uuid(scope_id)
        if pid is None or sid is None:
            return False
        scope_column = TaskRow.release_version_id if scope_type == "version" else TaskRow.iteration_id
        statement = select(TaskRow.id).where(
            TaskRow.project_id == pid,
            scope_column == sid,
            TaskRow.status.not_in(("done", "closed", "canceled")),
        ).limit(1)
        return self._session.scalar(statement) is not None

    def add(self, task: Task) -> None:
        self._session.add(TaskRow(**_task_values(task)))
        self._replace_participants(task)

    def save(self, task: Task, expected_version: int) -> bool:
        values = _task_values(task)
        values.pop("id")
        values.pop("project_id")
        values.pop("business_no")
        result = self._session.execute(
            update(TaskRow)
            .where(
                TaskRow.project_id == UUID(task.project_id),
                TaskRow.id == UUID(task.id),
                TaskRow.version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount == 1:
            self._replace_participants(task)
        return result.rowcount == 1

    def next_business_no(self) -> str:
        value = self._session.execute(text("SELECT nextval('task_business_no_seq')")).scalar_one()
        return f"TSK-{value:06d}"

    def get_worklog(self, project_id: str, task_id: str, worklog_id: str) -> Worklog | None:
        pid, tid, wid = _uuid(project_id), _uuid(task_id), _uuid(worklog_id)
        if None in (pid, tid, wid):
            return None
        row = self._session.scalar(
            select(WorklogRow).where(
                WorklogRow.project_id == pid, WorklogRow.task_id == tid, WorklogRow.id == wid
            )
        )
        return _worklog(row) if row else None

    def list_worklogs(self, project_id: str, task_id: str) -> list[Worklog]:
        pid, tid = _uuid(project_id), _uuid(task_id)
        if pid is None or tid is None:
            return []
        return [
            _worklog(row)
            for row in self._session.scalars(
                select(WorklogRow)
                .where(WorklogRow.project_id == pid, WorklogRow.task_id == tid)
                .order_by(WorklogRow.created_at, WorklogRow.id)
            )
        ]

    def append_worklog(self, worklog: Worklog) -> None:
        self._session.add(
            WorklogRow(
                id=UUID(worklog.id),
                project_id=UUID(worklog.project_id),
                task_id=UUID(worklog.task_id),
                user_id=worklog.user_id,
                recorded_by=worklog.recorded_by,
                work_date=worklog.work_date,
                minutes_delta=worklog.minutes_delta,
                description=worklog.description,
                corrects_worklog_id=UUID(worklog.corrects_worklog_id)
                if worklog.corrects_worklog_id
                else None,
                correction_reason=worklog.correction_reason,
                created_at=worklog.created_at,
            )
        )

    def sum_task_minutes(self, project_id: str, task_id: str) -> int:
        return int(
            self._session.scalar(
                select(func.coalesce(func.sum(WorklogRow.minutes_delta), 0)).where(
                    WorklogRow.project_id == UUID(project_id), WorklogRow.task_id == UUID(task_id)
                )
            )
            or 0
        )

    def sum_user_day_minutes(self, project_id: str, user_id: str, work_date: date) -> int:
        return int(
            self._session.scalar(
                select(func.coalesce(func.sum(WorklogRow.minutes_delta), 0)).where(
                    WorklogRow.project_id == UUID(project_id),
                    WorklogRow.user_id == user_id,
                    WorklogRow.work_date == work_date,
                )
            )
            or 0
        )

    def lock_worklog_scope(self, project_id: str, user_id: str, work_date: date) -> None:
        if self._session.bind is not None and self._session.bind.dialect.name == "postgresql":
            self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:value, 90421))"),
                {"value": f"{project_id}:{user_id}:{work_date}"},
            )

    def _replace_participants(self, task: Task) -> None:
        self._session.execute(
            delete(TaskParticipantRow).where(TaskParticipantRow.task_id == UUID(task.id))
        )
        self._session.add_all(
            [
                TaskParticipantRow(
                    project_id=UUID(task.project_id),
                    task_id=UUID(task.id),
                    user_id=user_id,
                    added_at=task.updated_at,
                    added_by=task.creator_id,
                )
                for user_id in task.participant_ids
            ]
        )

    def _to_task(self, row: TaskRow) -> Task:
        participants = list(
            self._session.scalars(
                select(TaskParticipantRow.user_id)
                .where(TaskParticipantRow.task_id == row.id)
                .order_by(TaskParticipantRow.user_id)
            )
        )
        task = Task(**{**_row_fields(row, Task), "participant_ids": participants})
        task.actual_minutes = max(0, self.sum_task_minutes(str(row.project_id), str(row.id)))
        return task


class SqlAlchemyAuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, item: AuditRecord) -> None:
        self._session.add(
            AuditRecordRow(
                id=UUID(item.id),
                occurred_at=item.occurred_at,
                trace_id=item.trace_id,
                actor_id=item.actor_id,
                project_id=UUID(item.project_id),
                resource_type=item.resource_type,
                resource_id=UUID(item.resource_id),
                action=item.action,
                result=item.result,
                before=item.before,
                after=item.after,
                reason=item.reason,
                source=item.source,
                idempotency_key=item.idempotency_key,
            )
        )


class SqlAlchemyOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, item: OutboxEvent) -> None:
        self._session.add(
            OutboxEventRow(
                id=UUID(item.id),
                event_type=item.event_type,
                event_version=item.event_version,
                aggregate_type=item.aggregate_type,
                aggregate_id=UUID(item.aggregate_id),
                project_id=UUID(item.project_id),
                payload=item.payload,
                trace_id=item.trace_id,
                occurred_at=item.occurred_at,
                available_at=item.occurred_at,
                status="pending",
                attempts=0,
            )
        )


def _row_fields(row, cls):
    return {name: getattr(row, name) for name in cls.__dataclass_fields__ if hasattr(row, name)}


def _project(row: ProjectRow) -> Project:
    return Project(**_row_fields(row, Project))


def _membership(row: ProjectMembershipRow) -> ProjectMembership:
    return ProjectMembership(
        id=str(row.id),
        project_id=str(row.project_id),
        user_id=row.user_id,
        role=Role(row.role),
        status=row.status,
        joined_at=row.joined_at,
        joined_by=row.joined_by,
        removed_at=row.removed_at,
        removed_by=row.removed_by,
        version=row.version,
    )


def _version(row: ReleaseVersionRow) -> ReleaseVersion:
    return ReleaseVersion(
        id=str(row.id),
        project_id=str(row.project_id),
        business_no=row.business_no,
        name=row.name,
        description=row.description,
        status=row.status,
        planned_release_date=row.planned_release_date,
        release_date=row.release_date,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _iteration(row: IterationRow) -> Iteration:
    return Iteration(
        id=str(row.id),
        project_id=str(row.project_id),
        business_no=row.business_no,
        name=row.name,
        goal=row.goal,
        start_date=row.start_date,
        end_date=row.end_date,
        capacity_minutes=row.capacity_minutes,
        status=row.status,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _worklog(row: WorklogRow) -> Worklog:
    return Worklog(
        id=str(row.id),
        project_id=str(row.project_id),
        task_id=str(row.task_id),
        user_id=row.user_id,
        recorded_by=row.recorded_by,
        work_date=row.work_date,
        minutes_delta=row.minutes_delta,
        description=row.description,
        corrects_worklog_id=str(row.corrects_worklog_id) if row.corrects_worklog_id else None,
        correction_reason=row.correction_reason,
        created_at=row.created_at,
    )


def _version_values(item: ReleaseVersion) -> dict:
    return {
        "id": UUID(item.id),
        "project_id": UUID(item.project_id),
        "business_no": item.business_no,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "planned_release_date": item.planned_release_date,
        "release_date": item.release_date,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _iteration_values(item: Iteration) -> dict:
    return {
        "id": UUID(item.id),
        "project_id": UUID(item.project_id),
        "business_no": item.business_no,
        "name": item.name,
        "goal": item.goal,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "capacity_minutes": item.capacity_minutes,
        "status": item.status,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _task_values(item: Task) -> dict:
    data = {name: getattr(item, name) for name in TaskRow.__table__.columns.keys()}
    data["id"] = UUID(item.id)
    data["project_id"] = UUID(item.project_id)
    data["release_version_id"] = UUID(item.release_version_id) if item.release_version_id else None
    data["iteration_id"] = UUID(item.iteration_id) if item.iteration_id else None
    return data
