"""Internal project authorization application helper."""

from collections.abc import Callable

from project_service.collaboration.policies import Action, AuthorizationPolicy
from project_service.persistence.uow import UnitOfWork
from project_service.shared.errors import ForbiddenError

ACTION_PERMISSION: dict[str, Action] = {
    "workflow.start": Action.CREATE_TASK,
    "workflow.transition": Action.TRANSITION_TASK,
    "workflow.read": Action.VIEW,
}


def check_authorization(
    uow_factory: Callable[[], UnitOfWork],
    actor_id: str,
    project_id: str,
    action: str,
) -> dict[str, object]:
    """Evaluate an internal workflow action against the project role policy."""
    with uow_factory() as uow:
        membership = uow.collaboration.get_active_membership(project_id, actor_id)
    if membership is None:
        return {
            "allowed": False,
            "reason_code": "NOT_PROJECT_MEMBER",
            "project_role": None,
        }
    required = ACTION_PERMISSION.get(action)
    if required is None:
        return {
            "allowed": False,
            "reason_code": "UNKNOWN_ACTION",
            "project_role": membership.role.value,
        }
    try:
        AuthorizationPolicy().authorize(membership.role, required)
    except ForbiddenError:
        return {
            "allowed": False,
            "reason_code": "PERMISSION_DENIED",
            "project_role": membership.role.value,
        }
    return {
        "allowed": True,
        "reason_code": "ALLOWED",
        "project_role": membership.role.value,
    }
