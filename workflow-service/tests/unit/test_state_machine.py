from workflow_service.workflows.models import TASK_DEFINITION, WorkflowInstance


def test_transition_and_optimistic_lock() -> None:
    item = WorkflowInstance(
        "i", "p", "task", "t", "system.task-lifecycle", 1, "todo", "u"
    )
    item.transition(TASK_DEFINITION, "start", "u", None, 1)
    assert item.current_state == "in_progress" and item.version == 2
    try:
        item.transition(TASK_DEFINITION, "complete", "u", None, 1)
        assert False
    except RuntimeError as error:
        assert str(error) == "VERSION_CONFLICT"
