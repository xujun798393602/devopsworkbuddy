from datetime import UTC, datetime

import pytest

from project_service.collaboration.models import Role
from project_service.shared.errors import ConflictError, ForbiddenError, VersionConflictError
from project_service.tasks.models import Task
from project_service.tasks.workflow import WorkflowV1


def task() -> Task:
    now = datetime.now(UTC)
    return Task(
        "t",
        "TSK-1",
        "p",
        "Title",
        "",
        "other",
        "p2",
        "todo",
        "u",
        None,
        "v",
        None,
        30,
        None,
        None,
        None,
        None,
        "task-default",
        1,
        1,
        now,
        now,
    )


def test_fixed_workflow_dates_and_reopen() -> None:
    item = task()
    flow = WorkflowV1()
    now = datetime.now(UTC)
    flow.transition(item, "in_progress", Role.MEMBER, now, 1)
    assert item.actual_start_at == now
    flow.transition(item, "done", Role.MEMBER, now, 2)
    assert item.actual_end_at == now
    flow.transition(item, "in_progress", Role.MEMBER, now, 3)
    assert item.actual_end_at is None


def test_invalid_lock_and_member_close_are_rejected() -> None:
    item = task()
    flow = WorkflowV1()
    with pytest.raises(VersionConflictError):
        flow.transition(item, "in_progress", Role.ADMIN, datetime.now(UTC), 2)
    item.status = "done"
    with pytest.raises(ForbiddenError):
        flow.transition(item, "closed", Role.MEMBER, datetime.now(UTC), 1)
    item.status = "todo"
    with pytest.raises(ConflictError):
        flow.transition(item, "done", Role.ADMIN, datetime.now(UTC), 1)
