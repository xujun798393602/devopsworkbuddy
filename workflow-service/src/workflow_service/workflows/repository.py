"""Workflow repositories for controlled tests and PostgreSQL production."""
from __future__ import annotations

from typing import Protocol

from workflow_service.workflows.models import (
    TASK_DEFINITION,
    WorkflowInstance,
    WorkflowTemplateVersion,
)


class WorkflowRepository(Protocol):
    """Storage contract consumed by workflow application services."""

    templates: dict[tuple[str, int], WorkflowTemplateVersion]
    instances: dict[str, WorkflowInstance]
    commands: dict[tuple[str, str], tuple[str, object]]
    outbox: list[dict[str, object]]

    def template(self, key: str, version: int) -> WorkflowTemplateVersion | None:
        """Return an exact immutable template version."""

    def instance(self, instance_id: str) -> WorkflowInstance | None:
        """Return one workflow instance."""

    def save_template(self, template: WorkflowTemplateVersion) -> None:
        """Persist a template version."""

    def save_instance(self, instance: WorkflowInstance) -> None:
        """Persist an instance and its transition history."""

    def command(self, actor_id: str, key: str) -> tuple[str, object] | None:
        """Return an idempotent command result when it exists."""

    def save_command(
        self,
        actor_id: str,
        key: str,
        signature: str,
        result: object,
    ) -> None:
        """Persist an idempotent command result."""

    def append_outbox(self, event: dict[str, object]) -> None:
        """Persist a transactional outbox event."""

    def list_instances(self, project_id: str) -> list[WorkflowInstance]:
        """List instances scoped to one project."""


class InMemoryWorkflowRepository:
    """Deterministic local adapter used only when explicitly injected."""

    def __init__(self) -> None:
        built_in = WorkflowTemplateVersion(
            "system.task-lifecycle", 1, "Task lifecycle", TASK_DEFINITION
        )
        built_in.publish()
        self.templates: dict[tuple[str, int], WorkflowTemplateVersion] = {
            (built_in.template_key, 1): built_in
        }
        self.instances: dict[str, WorkflowInstance] = {}
        self.commands: dict[tuple[str, str], tuple[str, object]] = {}
        self.outbox: list[dict[str, object]] = []

    def template(self, key: str, version: int) -> WorkflowTemplateVersion | None:
        return self.templates.get((key, version))

    def instance(self, instance_id: str) -> WorkflowInstance | None:
        return self.instances.get(instance_id)

    def save_template(self, template: WorkflowTemplateVersion) -> None:
        self.templates[(template.template_key, template.version_no)] = template

    def save_instance(self, instance: WorkflowInstance) -> None:
        self.instances[instance.id] = instance

    def command(self, actor_id: str, key: str) -> tuple[str, object] | None:
        return self.commands.get((actor_id, key))

    def save_command(
        self,
        actor_id: str,
        key: str,
        signature: str,
        result: object,
    ) -> None:
        self.commands[(actor_id, key)] = (signature, result)

    def append_outbox(self, event: dict[str, object]) -> None:
        self.outbox.append(event)

    def list_instances(self, project_id: str) -> list[WorkflowInstance]:
        return [item for item in self.instances.values() if item.project_id == project_id]
