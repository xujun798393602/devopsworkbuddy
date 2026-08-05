"""Fixed task workflow template version one."""

from __future__ import annotations

from datetime import datetime

from project_service.collaboration.models import Role
from project_service.shared.errors import ConflictError, ForbiddenError, VersionConflictError
from project_service.tasks.models import Task


class WorkflowV1:
    """Apply explicit fixed task state transitions."""

    transitions = {
        "todo": {"in_progress", "canceled"},
        "in_progress": {"done", "canceled"},
        "done": {"closed", "in_progress"},
    }

    def allowed_targets(self, status: str, role: Role) -> set[str]:
        targets = set(self.transitions.get(status, set()))
        if role == Role.MEMBER:
            targets.discard("closed")
        return targets

    def transition(
        self,
        task: Task,
        target: str,
        role: Role,
        now: datetime,
        expected_version: int | None = None,
    ) -> Task:
        if expected_version is not None and task.version != expected_version:
            raise VersionConflictError()
        if target not in self.transitions.get(task.status, set()):
            raise ConflictError("Invalid task state transition", "INVALID_STATE_TRANSITION")
        if target not in self.allowed_targets(task.status, role):
            raise ForbiddenError()
        if target == "in_progress" and task.actual_start_at is None:
            task.actual_start_at = now
        if target == "done":
            task.actual_end_at = now
        if task.status == "done" and target == "in_progress":
            task.actual_end_at = None
        task.status = target
        task.updated_at = now
        task.version += 1
        return task
