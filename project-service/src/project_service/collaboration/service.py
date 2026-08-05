"""Members, ownership, versions, and iterations application service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import uuid4

from project_service.collaboration.models import Iteration, ProjectMembership, ReleaseVersion, Role
from project_service.collaboration.policies import Action, AuthorizationPolicy
from project_service.persistence.uow import UnitOfWork
from project_service.shared.audit import make_audit, make_outbox
from project_service.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from project_service.shared.idempotency import IdempotencyExecutor, StoredResponse
from project_service.shared.request_context import RequestContext


class CollaborationService:
    """Execute project collaboration use cases within one UoW each."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        clock: Callable[[], datetime] | None = None,
        idempotency: IdempotencyExecutor | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._policy = AuthorizationPolicy()
        self._idempotency = idempotency or IdempotencyExecutor()

    def _access(self, uow: UnitOfWork, project_id: str, context: RequestContext, action: Action):
        membership = uow.collaboration.get_active_membership(project_id, context.actor_id)
        if membership is None:
            raise NotFoundError()
        project = uow.projects.get(project_id)
        if project is None:
            raise NotFoundError()
        if action != Action.VIEW and project.status == "archived":
            raise ConflictError("Archived projects are read-only", "PROJECT_ARCHIVED")
        self._policy.authorize(membership.role, action)
        return membership, project

    def list_members(self, project_id: str, context: RequestContext) -> list[ProjectMembership]:
        with self._uow_factory() as uow:
            self._access(uow, project_id, context, Action.VIEW)
            return uow.collaboration.list_members(project_id)

    def add_member(self, project_id: str, command: dict[str, object], context: RequestContext, key: str) -> StoredResponse:
        user_id = str(command.get("user_id", "")).strip()
        try:
            role = Role(str(command.get("role", "member")))
        except ValueError as error:
            raise ValidationError("role is invalid") from error
        if not user_id or role == Role.OWNER:
            raise ValidationError("user_id is required and owner must use transfer")
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                self._access(uow, project_id, context, Action.MANAGE_MEMBERS)
                existing = uow.collaboration.get_active_membership(project_id, user_id)
                if existing:
                    return self._response(existing.to_dict(), 200, existing.version, context)
                now = self._clock()
                item = ProjectMembership(str(uuid4()), project_id, user_id, role, "active", now, context.actor_id)
                uow.collaboration.add_membership(item)
                self._record(uow, context, key, project_id, "membership", item.id, "membership.added", {}, {"user_id": user_id, "role": role.value})
                return self._response(item.to_dict(), 201, item.version, context)
            return self._execute(uow, context, key, "POST /projects/{project_id}/members", {"project_id": project_id}, command, None, write)

    def change_member_role(self, project_id: str, membership_id: str, role_value: str, expected: int, context: RequestContext, key: str) -> StoredResponse:
        command = {"role": role_value}
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                self._access(uow, project_id, context, Action.MANAGE_MEMBERS)
                item = uow.collaboration.get_membership(project_id, membership_id, for_update=True)
                if item is None:
                    raise NotFoundError()
                before = {"role": item.role.value}
                try:
                    role = Role(role_value)
                except ValueError as error:
                    raise ValidationError("role is invalid") from error
                item.change_role(role, expected)
                if not uow.collaboration.save_membership(item, expected):
                    raise VersionConflictError()
                self._record(uow, context, key, project_id, "membership", item.id, "membership.role_changed", before, {"role": item.role.value})
                return self._response(item.to_dict(), 200, item.version, context)
            return self._execute(uow, context, key, "PATCH /projects/{project_id}/members/{membership_id}", {"project_id": project_id, "membership_id": membership_id}, command, expected, write)

    def remove_member(self, project_id: str, membership_id: str, expected: int, context: RequestContext, key: str) -> StoredResponse:
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                self._access(uow, project_id, context, Action.MANAGE_MEMBERS)
                item = uow.collaboration.get_membership(project_id, membership_id, for_update=True)
                if item is None:
                    raise NotFoundError()
                item.remove(context.actor_id, expected, self._clock())
                if not uow.collaboration.save_membership(item, expected):
                    raise VersionConflictError()
                self._record(uow, context, key, project_id, "membership", item.id, "membership.removed", {}, {"status": "removed"})
                return StoredResponse(204, None, {})
            return self._execute(uow, context, key, "DELETE /projects/{project_id}/members/{membership_id}", {"project_id": project_id, "membership_id": membership_id}, {}, expected, write)

    def transfer_owner(self, project_id: str, command: dict[str, object], context: RequestContext, key: str) -> StoredResponse:
        target_user = str(command.get("new_owner_user_id", "")).strip()
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                current, project = self._access(uow, project_id, context, Action.TRANSFER_OWNER)
                target = uow.collaboration.get_active_membership(project_id, target_user, for_update=True)
                if target is None:
                    raise ValidationError("new owner must be an active member")
                if target.role == Role.VIEWER:
                    raise ValidationError("Viewer cannot become Owner")
                old_current, old_target = current.version, target.version
                # One SQL statement avoids an intermediate violation of the partial unique Owner index.
                if not uow.collaboration.transfer_owner_roles(project_id, current.id, target.id, old_current, old_target):
                    raise VersionConflictError()
                current.role, target.role = Role.ADMIN, Role.OWNER
                current.version += 1
                target.version += 1
                old_project = project.version
                project.owner_id = target.user_id
                project.version += 1
                project.updated_at = self._clock()
                if not uow.projects.save(project, old_project):
                    raise VersionConflictError()
                self._record(uow, context, key, project_id, "project", project_id, "owner.transferred", {"owner_id": current.user_id}, {"owner_id": target.user_id})
                data = {"previous_owner": current.to_dict(), "new_owner": target.to_dict()}
                return self._response(data, 200, project.version, context)
            return self._execute(uow, context, key, "POST /projects/{project_id}/owner-transfers", {"project_id": project_id}, command, None, write)

    def list_versions(self, project_id: str, context: RequestContext) -> list[ReleaseVersion]:
        with self._uow_factory() as uow:
            self._access(uow, project_id, context, Action.VIEW)
            return uow.collaboration.list_versions(project_id)

    def get_version(self, project_id: str, resource_id: str, context: RequestContext) -> ReleaseVersion:
        with self._uow_factory() as uow:
            self._access(uow, project_id, context, Action.VIEW)
            item = uow.collaboration.get_version(project_id, resource_id)
            if item is None:
                raise NotFoundError()
            return item

    def create_version(self, project_id: str, command: dict[str, object], context: RequestContext, key: str) -> StoredResponse:
        name = str(command.get("name", "")).strip()
        if not 1 <= len(name) <= 120:
            raise ValidationError("name must contain 1 to 120 characters")
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                self._access(uow, project_id, context, Action.MANAGE_PLAN)
                now = self._clock()
                number = uow.collaboration.next_counter(project_id, "version")
                item = ReleaseVersion(str(uuid4()), project_id, f"VER-{number}", name, str(command.get("description", "")), "planned", _date(command.get("planned_release_date")), None, 1, now, now)
                uow.collaboration.add_version(item)
                self._record(uow, context, key, project_id, "version", item.id, "version.created", {}, item.to_dict())
                return self._response(item.to_dict(), 201, item.version, context)
            return self._execute(uow, context, key, "POST /projects/{project_id}/versions", {"project_id": project_id}, command, None, write)

    def update_version(self, project_id: str, resource_id: str, command: dict[str, object], expected: int, context: RequestContext, key: str) -> StoredResponse:
        return self._change_plan("version", project_id, resource_id, command, expected, context, key, False)

    def transition_version(self, project_id: str, resource_id: str, command: dict[str, object], context: RequestContext, key: str, expected: int) -> StoredResponse:
        return self._change_plan("version", project_id, resource_id, command, expected, context, key, True)

    def list_iterations(self, project_id: str, context: RequestContext) -> list[Iteration]:
        with self._uow_factory() as uow:
            self._access(uow, project_id, context, Action.VIEW)
            return uow.collaboration.list_iterations(project_id)

    def get_iteration(self, project_id: str, resource_id: str, context: RequestContext) -> Iteration:
        with self._uow_factory() as uow:
            self._access(uow, project_id, context, Action.VIEW)
            item = uow.collaboration.get_iteration(project_id, resource_id)
            if item is None:
                raise NotFoundError()
            return item

    def create_iteration(self, project_id: str, command: dict[str, object], context: RequestContext, key: str) -> StoredResponse:
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                self._access(uow, project_id, context, Action.MANAGE_PLAN)
                now = self._clock()
                number = uow.collaboration.next_counter(project_id, "iteration")
                item = Iteration(str(uuid4()), project_id, f"ITR-{number}", str(command.get("name", "")).strip(), str(command.get("goal", "")), _date(command.get("start_date"), True), _date(command.get("end_date"), True), command.get("capacity_minutes"), "planned", 1, now, now)
                uow.collaboration.add_iteration(item)
                self._record(uow, context, key, project_id, "iteration", item.id, "iteration.created", {}, item.to_dict())
                return self._response(item.to_dict(), 201, item.version, context)
            return self._execute(uow, context, key, "POST /projects/{project_id}/iterations", {"project_id": project_id}, command, None, write)

    def update_iteration(self, project_id: str, resource_id: str, command: dict[str, object], expected: int, context: RequestContext, key: str) -> StoredResponse:
        return self._change_plan("iteration", project_id, resource_id, command, expected, context, key, False)

    def transition_iteration(self, project_id: str, resource_id: str, command: dict[str, object], context: RequestContext, key: str, expected: int) -> StoredResponse:
        return self._change_plan("iteration", project_id, resource_id, command, expected, context, key, True)

    def _change_plan(self, kind: str, project_id: str, resource_id: str, command: dict[str, object], expected: int, context: RequestContext, key: str, transition: bool) -> StoredResponse:
        operation = f"{'POST' if transition else 'PATCH'} /projects/{{project_id}}/{kind}s/{{resource_id}}{'/transitions' if transition else ''}"
        with self._uow_factory() as uow:
            def write() -> StoredResponse:
                self._access(uow, project_id, context, Action.MANAGE_PLAN)
                getter = uow.collaboration.get_version if kind == "version" else uow.collaboration.get_iteration
                saver = uow.collaboration.save_version if kind == "version" else uow.collaboration.save_iteration
                item = getter(project_id, resource_id, for_update=True)
                if item is None:
                    raise NotFoundError()
                before = item.to_dict()
                if transition:
                    target = str(command.get("target_status", ""))
                    force = bool(command.get("force", False))
                    reason = str(command.get("reason", "")).strip() or None
                    terminal = (kind == "version" and target == "released") or (kind == "iteration" and target == "completed")
                    if terminal and uow.tasks.has_open_tasks(project_id, kind, resource_id):
                        if not force:
                            raise ConflictError("Associated tasks are not finished", "OPEN_TASKS_EXIST")
                        if reason is None:
                            raise ValidationError("reason is required when force=true")
                    if force and reason is None:
                        raise ValidationError("reason is required when force=true")
                    if item.version != expected:
                        raise VersionConflictError()
                    if kind == "version":
                        item.transition(target, force, reason, self._clock().date())
                    else:
                        item.transition(target, force, reason)
                else:
                    reason = None
                    item.update(command, expected)
                item.updated_at = self._clock()
                if not saver(item, expected):
                    raise VersionConflictError()
                action = f"{kind}.{'transitioned' if transition else 'updated'}"
                self._record(uow, context, key, project_id, kind, item.id, action, before, item.to_dict(), reason)
                return self._response(item.to_dict(), 200, item.version, context)
            return self._execute(uow, context, key, operation, {"project_id": project_id, "resource_id": resource_id}, command, expected, write)

    def _execute(self, uow, context, key, operation, path, body, expected, handler) -> StoredResponse:
        return self._idempotency.execute(uow, actor_id=context.actor_id, key=key, operation=operation, path=path, body=body, expected_version=expected, handler=handler)

    @staticmethod
    def _response(data, status: int, version: int | None, context: RequestContext) -> StoredResponse:
        headers = {"ETag": f'"{version}"'} if version is not None else {}
        return StoredResponse(status, {"data": data, "meta": {"trace_id": context.trace_id}}, headers)

    @staticmethod
    def _record(uow, context, key, project_id, resource_type, resource_id, action, before, after, reason=None) -> None:
        uow.audit.append(make_audit(trace_id=context.trace_id, actor_id=context.actor_id, project_id=project_id, resource_type=resource_type, resource_id=resource_id, action=action, before=before, after=after, reason=reason, idempotency_key=key))
        uow.outbox.append(make_outbox(event_type=f"{action}.v1", aggregate_type=resource_type, aggregate_id=resource_id, project_id=project_id, payload={"resource_id": resource_id, "action": action, "reason": reason}, trace_id=context.trace_id))


def _date(value: object, required: bool = False) -> date | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValidationError("date fields must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError("date fields must use YYYY-MM-DD") from error
