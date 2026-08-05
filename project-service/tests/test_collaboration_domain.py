from datetime import UTC, date, datetime

import pytest

from project_service.collaboration.models import Iteration, ProjectMembership, Role
from project_service.collaboration.policies import Action, AuthorizationPolicy
from project_service.shared.errors import ConflictError, ForbiddenError, VersionConflictError


def test_owner_cannot_be_changed_or_removed_normally() -> None:
    membership = ProjectMembership("m", "p", "u", Role.OWNER, "active", datetime.now(UTC), "u")
    with pytest.raises(ConflictError):
        membership.change_role(Role.ADMIN, 1)
    with pytest.raises(ConflictError):
        membership.remove("u", 1, datetime.now(UTC))


def test_membership_uses_optimistic_lock() -> None:
    membership = ProjectMembership("m", "p", "u", Role.MEMBER, "active", datetime.now(UTC), "o")
    with pytest.raises(VersionConflictError):
        membership.change_role(Role.ADMIN, 2)


def test_policy_matrix_and_viewer_worklog_redaction() -> None:
    policy = AuthorizationPolicy()
    policy.authorize(Role.ADMIN, Action.MANAGE_PLAN)
    assert not policy.can_view_worklog_detail(Role.VIEWER)
    with pytest.raises(ForbiddenError):
        policy.authorize(Role.VIEWER, Action.CREATE_TASK)


def test_iteration_dates_and_state_machine() -> None:
    item = Iteration(
        "i",
        "p",
        "ITR-1",
        "Sprint",
        "",
        date(2026, 1, 1),
        date(2026, 1, 2),
        None,
        "planned",
        1,
        datetime.now(UTC),
        datetime.now(UTC),
    )
    item.transition("active", False, None)
    assert item.status == "active" and item.version == 2
    with pytest.raises(ConflictError):
        item.transition("planned", False, None)
