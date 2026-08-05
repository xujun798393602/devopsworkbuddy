"""Project role authorization policy."""

from __future__ import annotations

from enum import StrEnum

from project_service.collaboration.models import Role
from project_service.shared.errors import ForbiddenError


class Action(StrEnum):
    VIEW = "view"
    MANAGE_MEMBERS = "manage_members"
    TRANSFER_OWNER = "transfer_owner"
    MANAGE_PLAN = "manage_plan"
    CREATE_TASK = "create_task"
    EDIT_TASK = "edit_task"
    TRANSITION_TASK = "transition_task"
    RECORD_WORKLOG = "record_worklog"
    VIEW_WORKLOG = "view_worklog"


class AuthorizationPolicy:
    """Enforces the fixed P0 role matrix."""

    _allowed = {
        Action.VIEW: set(Role),
        Action.MANAGE_MEMBERS: {Role.OWNER, Role.ADMIN},
        Action.TRANSFER_OWNER: {Role.OWNER},
        Action.MANAGE_PLAN: {Role.OWNER, Role.ADMIN},
        Action.CREATE_TASK: {Role.OWNER, Role.ADMIN, Role.MEMBER},
        Action.EDIT_TASK: {Role.OWNER, Role.ADMIN, Role.MEMBER},
        Action.TRANSITION_TASK: {Role.OWNER, Role.ADMIN, Role.MEMBER},
        Action.RECORD_WORKLOG: {Role.OWNER, Role.ADMIN, Role.MEMBER},
        Action.VIEW_WORKLOG: {Role.OWNER, Role.ADMIN, Role.MEMBER},
    }

    def authorize(
        self, role: Role, action: Action, task_context: dict[str, object] | None = None
    ) -> None:
        if role not in self._allowed[action]:
            raise ForbiddenError()
        if role == Role.MEMBER and action in {Action.EDIT_TASK, Action.TRANSITION_TASK}:
            context = task_context or {}
            actor_id = context.get("actor_id")
            related = actor_id in {
                context.get("creator_id"),
                context.get("assignee_id"),
            } or actor_id in context.get("participant_ids", [])
            if not related:
                raise ForbiddenError("Members may only change related tasks")

    def can_view_worklog_detail(self, role: Role) -> bool:
        return role != Role.VIEWER
