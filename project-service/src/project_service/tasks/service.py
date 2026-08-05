"""Task and immutable Worklog application service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from project_service.collaboration.models import Role
from project_service.collaboration.policies import Action, AuthorizationPolicy
from project_service.persistence.uow import UnitOfWork
from project_service.shared.audit import make_audit, make_outbox
from project_service.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from project_service.shared.idempotency import IdempotencyExecutor, StoredResponse
from project_service.shared.request_context import RequestContext
from project_service.tasks.models import Task, Worklog
from project_service.tasks.workflow import WorkflowV1


@dataclass(slots=True)
class TaskPage:
    """Stable cursor page of project-scoped tasks."""

    items: list[Task]
    next_cursor: str | None
    has_more: bool


class TaskService:
    """Execute task and Worklog use cases without leaking ORM rows."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], policy: AuthorizationPolicy | None = None, workflow: WorkflowV1 | None = None, clock: Callable[[], datetime] | None = None, idempotency: IdempotencyExecutor | None = None) -> None:
        self._uow_factory = uow_factory
        self._policy = policy or AuthorizationPolicy()
        self._workflow = workflow or WorkflowV1()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._idempotency = idempotency or IdempotencyExecutor()

    def _access(self, uow, project_id, context, action, task=None):
        membership = uow.collaboration.get_active_membership(project_id, context.actor_id)
        if membership is None:
            raise NotFoundError()
        project = uow.projects.get(project_id)
        if project is None:
            raise NotFoundError()
        if action != Action.VIEW and project.status == "archived":
            raise ConflictError("Archived projects are read-only", "PROJECT_ARCHIVED")
        task_context = None if task is None else {"actor_id": context.actor_id, "creator_id": task.creator_id, "assignee_id": task.assignee_id, "participant_ids": task.participant_ids}
        self._policy.authorize(membership.role, action, task_context)
        return membership

    def list_tasks(self, project_id: str, context: RequestContext, limit: int = 50, after: tuple[str, str] | None = None) -> TaskPage:
        with self._uow_factory() as uow:
            self._access(uow, project_id, context, Action.VIEW)
            items = uow.tasks.list(project_id, limit + 1, after)
            has_more = len(items) > limit
            visible = items[:limit]
            next_cursor = None
            if has_more and visible:
                from project_service.shared.http import encode_cursor
                last = visible[-1]
                next_cursor = encode_cursor(project_id, last.created_at.isoformat(), last.id)
            return TaskPage(visible, next_cursor, has_more)

    def get_task(self, project_id: str, task_id: str, context: RequestContext) -> Task:
        with self._uow_factory() as uow:
            self._access(uow, project_id, context, Action.VIEW)
            task = uow.tasks.get(project_id, task_id)
            if task is None:
                raise NotFoundError()
            return task

    def create_task(self, project_id: str, command: dict[str, object], context: RequestContext, key: str) -> StoredResponse:
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                self._access(uow, project_id, context, Action.CREATE_TASK)
                release_id, iteration_id = command.get("release_version_id"), command.get("iteration_id")
                self._validate_scope(uow, project_id, release_id, iteration_id)
                participants = _strings(command.get("participant_ids", []))
                assignee = command.get("assignee_id")
                self._validate_people(uow, project_id, [assignee, *participants])
                now = self._clock()
                task = Task(str(uuid4()), uow.tasks.next_business_no(), project_id, _required(command, "title", 200), str(command.get("description", "")), str(command.get("task_type", "other")), str(command.get("priority", "p2")), "todo", context.actor_id, assignee, release_id, iteration_id, int(command.get("estimated_minutes", 0)), _datetime(command.get("planned_start_at")), _datetime(command.get("planned_end_at")), None, None, "task-default", 1, 1, now, now, participants)
                uow.tasks.add(task)
                self._record(uow, context, key, task, "task.created", {}, task.to_dict())
                return self._response(task.to_dict(), 201, task.version, context)
            return self._execute(uow, context, key, "POST /projects/{project_id}/tasks", {"project_id": project_id}, command, None, write)

    def update_task(self, project_id: str, task_id: str, command: dict[str, object], expected: int, context: RequestContext, key: str) -> StoredResponse:
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                task = uow.tasks.get(project_id, task_id, for_update=True)
                if task is None:
                    raise NotFoundError()
                membership = self._access(uow, project_id, context, Action.EDIT_TASK, task)
                fields = dict(command)
                if membership.role == Role.MEMBER and ({"assignee_id", "participant_ids", "release_version_id", "iteration_id"} & fields.keys()):
                    raise ForbiddenError("Members cannot assign or re-scope tasks")
                self._validate_scope(uow, project_id, fields.get("release_version_id", task.release_version_id), fields.get("iteration_id", task.iteration_id))
                self._validate_people(uow, project_id, [fields.get("assignee_id", task.assignee_id), *_strings(fields.get("participant_ids", task.participant_ids))])
                for field in ("planned_start_at", "planned_end_at"):
                    if field in fields:
                        fields[field] = _datetime(fields[field])
                before = task.to_dict()
                task.update(fields, expected)
                task.updated_at = self._clock()
                if not uow.tasks.save(task, expected):
                    raise VersionConflictError()
                self._record(uow, context, key, task, "task.updated", before, task.to_dict())
                return self._response(task.to_dict(), 200, task.version, context)
            return self._execute(uow, context, key, "PATCH /projects/{project_id}/tasks/{task_id}", {"project_id": project_id, "task_id": task_id}, command, expected, write)

    def transition_task(self, project_id: str, task_id: str, command: dict[str, object], expected: int, context: RequestContext, key: str) -> StoredResponse:
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                task = uow.tasks.get(project_id, task_id, for_update=True)
                if task is None:
                    raise NotFoundError()
                membership = self._access(uow, project_id, context, Action.TRANSITION_TASK, task)
                before = task.to_dict()
                self._workflow.transition(task, str(command.get("target_status", "")), membership.role, self._clock(), expected)
                if not uow.tasks.save(task, expected):
                    raise VersionConflictError()
                self._record(uow, context, key, task, "task.transitioned", before, task.to_dict())
                return self._response(task.to_dict(), 200, task.version, context)
            return self._execute(uow, context, key, "POST /projects/{project_id}/tasks/{task_id}/transitions", {"project_id": project_id, "task_id": task_id}, command, expected, write)

    def list_worklogs(self, project_id: str, task_id: str, context: RequestContext) -> list[Worklog]:
        with self._uow_factory() as uow:
            membership = self._access(uow, project_id, context, Action.VIEW_WORKLOG)
            if not self._policy.can_view_worklog_detail(membership.role):
                raise ForbiddenError()
            if uow.tasks.get(project_id, task_id) is None:
                raise NotFoundError()
            return uow.tasks.list_worklogs(project_id, task_id)

    def record_worklog(self, project_id: str, task_id: str, command: dict[str, object], context: RequestContext, key: str) -> StoredResponse:
        return self._append_worklog(project_id, task_id, None, command, context, key)

    def correct_worklog(self, project_id: str, task_id: str, worklog_id: str, command: dict[str, object], context: RequestContext, key: str) -> StoredResponse:
        return self._append_worklog(project_id, task_id, worklog_id, command, context, key)

    def _append_worklog(self, project_id, task_id, corrects, command, context, key) -> StoredResponse:
        operation = "POST /projects/{project_id}/tasks/{task_id}/worklogs" if corrects is None else "POST /projects/{project_id}/tasks/{task_id}/worklogs/{worklog_id}/corrections"
        path = {"project_id": project_id, "task_id": task_id}
        if corrects:
            path["worklog_id"] = corrects
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                task = uow.tasks.get(project_id, task_id, for_update=True)
                if task is None:
                    raise NotFoundError()
                membership = self._access(uow, project_id, context, Action.RECORD_WORKLOG)
                user_id = str(command.get("user_id", context.actor_id))
                reason = str(command.get("correction_reason", "")).strip() or None
                if user_id != context.actor_id and membership.role not in {Role.OWNER, Role.ADMIN}:
                    raise ForbiddenError()
                if user_id != context.actor_id and not reason:
                    raise ValidationError("correction_reason is required for on-behalf recording")
                if task.status in {"closed", "canceled"}:
                    raise ConflictError("Task does not accept Worklogs", "INVALID_TASK_STATE")
                work_date = _date(command.get("work_date"))
                now = self._clock()
                if work_date > now.date():
                    raise ValidationError("work_date cannot be in the future")
                if task.status == "done" and task.actual_end_at and work_date > task.actual_end_at.date():
                    raise ValidationError("Worklog date is after task completion")
                original = uow.tasks.get_worklog(project_id, task_id, corrects) if corrects else None
                if corrects and (original is None or original.user_id != user_id):
                    raise ValidationError("Correction target must belong to the same task and user")
                delta = int(command.get("minutes_delta", 0))
                uow.tasks.lock_worklog_scope(project_id, user_id, work_date)
                task_total = uow.tasks.sum_task_minutes(project_id, task_id)
                day_total = uow.tasks.sum_user_day_minutes(project_id, user_id, work_date)
                if task_total + delta < 0:
                    raise ConflictError("Correction would make task actual minutes negative", "WORKLOG_NEGATIVE_TOTAL")
                if day_total + delta > 1440:
                    raise ConflictError("Daily Worklog total exceeds 1440 minutes", "WORKLOG_DAILY_LIMIT")
                item = Worklog(str(uuid4()), project_id, task_id, user_id, context.actor_id, work_date, delta, _required(command, "description", 2000), corrects, reason, now)
                uow.tasks.append_worklog(item)
                task.actual_minutes = task_total + delta
                self._record(uow, context, key, task, "worklog.corrected" if corrects else "worklog.recorded", {}, {"worklog_id": item.id, "minutes_delta": delta, "user_id": user_id})
                return self._response(item.to_dict(), 201, None, context)
            return self._execute(uow, context, key, operation, path, command, None, write)

    def _validate_scope(self, uow, project_id, release_id, iteration_id):
        if not release_id and not iteration_id:
            raise ValidationError("A task must reference a version or iteration")
        if release_id:
            item = uow.collaboration.get_version(project_id, release_id)
            if item is None:
                raise NotFoundError()
            if item.status in {"released", "canceled", "archived"}:
                raise ConflictError("Version cannot accept tasks")
        if iteration_id:
            item = uow.collaboration.get_iteration(project_id, iteration_id)
            if item is None:
                raise NotFoundError()
            if item.status in {"completed", "canceled"}:
                raise ConflictError("Iteration cannot accept tasks")

    @staticmethod
    def _validate_people(uow, project_id, users):
        for user_id in {value for value in users if value}:
            membership = uow.collaboration.get_active_membership(project_id, user_id)
            if membership is None or membership.role == Role.VIEWER:
                raise ValidationError("Assignees and participants must be active non-Viewer members")

    def _execute(self, uow, context, key, operation, path, body, expected, handler) -> StoredResponse:
        return self._idempotency.execute(uow, actor_id=context.actor_id, key=key, operation=operation, path=path, body=body, expected_version=expected, handler=handler)

    @staticmethod
    def _response(data, status, version, context) -> StoredResponse:
        headers = {"ETag": f'"{version}"'} if version is not None else {}
        return StoredResponse(status, {"data": data, "meta": {"trace_id": context.trace_id}}, headers)

    @staticmethod
    def _record(uow, context, key, task, action, before, after):
        uow.audit.append(make_audit(trace_id=context.trace_id, actor_id=context.actor_id, project_id=task.project_id, resource_type="task", resource_id=task.id, action=action, before=before, after=after, idempotency_key=key))
        uow.outbox.append(make_outbox(event_type=f"{action}.v1", aggregate_type="task", aggregate_id=task.id, project_id=task.project_id, payload={"task_id": task.id, "action": action}, trace_id=context.trace_id))


def _required(command, field, maximum):
    value = command.get(field)
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValidationError(f"{field} is required and must not exceed {maximum} characters")
    return value.strip()


def _strings(value):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError("participant_ids must be an array of strings")
    return list(dict.fromkeys(value))


def _datetime(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("datetime fields must be ISO 8601 strings")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError("datetime fields must be ISO 8601 strings") from error


def _date(value):
    if not isinstance(value, str):
        raise ValidationError("work_date is required")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError("work_date must use YYYY-MM-DD") from error
