"""Workflow aggregates and immutable template versions."""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

TASK_DEFINITION = {
    "states": ["todo", "in_progress", "done", "closed", "canceled"],
    "initial_state": "todo",
    "terminal_states": ["closed", "canceled"],
    "transitions": [
        {"action": "start", "from": "todo", "to": "in_progress"},
        {"action": "complete", "from": "in_progress", "to": "done"},
        {"action": "close", "from": "done", "to": "closed"},
        {"action": "cancel", "from": "todo", "to": "canceled"},
        {"action": "cancel", "from": "in_progress", "to": "canceled"},
        {"action": "reopen", "from": "done", "to": "in_progress"},
        {"action": "reopen", "from": "closed", "to": "in_progress"},
    ],
}


@dataclass(slots=True)
class WorkflowTemplateVersion:
    template_key: str
    version_no: int
    name: str
    definition: dict[str, object]
    status: str = "draft"

    def publish(self) -> None:
        if self.status != "draft":
            raise ValueError("Only draft versions can be published")
        self.status = "published"

    def deprecate(self) -> None:
        if self.status != "published":
            raise ValueError("Only published versions can be deprecated")
        self.status = "deprecated"


@dataclass(slots=True)
class WorkflowTransition:
    id: str
    from_state: str
    to_state: str
    action: str
    actor_id: str
    reason: str | None
    occurred_at: datetime


@dataclass(slots=True)
class WorkflowInstance:
    id: str
    project_id: str
    business_object_type: str
    business_object_id: str
    template_key: str
    template_version: int
    current_state: str
    started_by: str
    status: str = "active"
    version: int = 1
    history: list[WorkflowTransition] = field(default_factory=list)

    def transition(
        self,
        definition: dict[str, object],
        action: str,
        actor_id: str,
        reason: str | None,
        expected_version: int,
    ) -> WorkflowTransition:
        if expected_version != self.version:
            raise RuntimeError("VERSION_CONFLICT")
        candidate = next(
            (
                item
                for item in definition["transitions"]
                if item["action"] == action and item["from"] == self.current_state
            ),
            None,
        )
        if candidate is None:
            raise ValueError("INVALID_TRANSITION")
        item = WorkflowTransition(
            str(uuid4()),
            self.current_state,
            str(candidate["to"]),
            action,
            actor_id,
            reason,
            datetime.now(UTC),
        )
        self.current_state = item.to_state
        self.version += 1
        self.history.append(item)
        if self.current_state in definition["terminal_states"]:
            self.status = (
                "completed" if self.current_state == "closed" else "canceled"
            )
        return item
