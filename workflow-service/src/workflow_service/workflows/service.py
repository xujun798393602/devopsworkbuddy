"""Workflow application service with authorization, idempotency, and outbox."""
import hashlib
import json
from uuid import uuid4

from workflow_service.integrations.project_authorization import ProjectAuthorizationPort
from workflow_service.workflows.models import WorkflowInstance
from workflow_service.workflows.repository import WorkflowRepository


class WorkflowService:
    def __init__(
        self, repo: WorkflowRepository, authorizer: ProjectAuthorizationPort
    ) -> None:
        self.repo, self.authorizer = repo, authorizer

    def start(
        self, payload: dict[str, object], actor_id: str, key: str
    ) -> WorkflowInstance:
        project_id = str(payload["project_id"])
        signature = canonical(payload)
        existing = self.repo.command(actor_id, key)
        if existing:
            if existing[0] != signature:
                raise RuntimeError("IDEMPOTENCY_KEY_CONFLICT")
            return existing[1]  # type: ignore[return-value]
        resource = {
            "type": str(payload["business_object_type"]),
            "id": str(payload["business_object_id"]),
        }
        if not self.authorizer.check(
            actor_id, project_id, "workflow.start", resource
        ):
            raise PermissionError("PROJECT_SCOPE_DENIED")
        template = self.repo.template(
            str(payload.get("template_key", "system.task-lifecycle")),
            int(payload.get("template_version", 1)),
        )
        if template is None or template.status != "published":
            raise ValueError("TEMPLATE_NOT_PUBLISHED")
        instance = WorkflowInstance(
            str(uuid4()),
            project_id,
            str(payload["business_object_type"]),
            str(payload["business_object_id"]),
            template.template_key,
            template.version_no,
            str(template.definition["initial_state"]),
            actor_id,
        )
        self.repo.save_instance(instance)
        self.repo.save_command(actor_id, key, signature, instance)
        self.repo.append_outbox(
            {
                "event_type": "Workflow.InstanceStarted",
                "event_version": 1,
                "project_id": project_id,
                "data": {"instance_id": instance.id},
            }
        )
        return instance

    def transition(
        self,
        instance_id: str,
        action: str,
        actor_id: str,
        reason: str | None,
        expected_version: int,
        key: str,
    ) -> WorkflowInstance:
        instance = self.repo.instance(instance_id)
        if instance is None:
            raise LookupError("NOT_FOUND")
        resource = {
            "type": instance.business_object_type,
            "id": instance.business_object_id,
        }
        if not self.authorizer.check(
            actor_id, instance.project_id, "workflow.transition", resource
        ):
            raise LookupError("NOT_FOUND")
        template = self.repo.template(
            instance.template_key, instance.template_version
        )
        assert template is not None
        command = {
            "instance_id": instance_id,
            "action": action,
            "reason": reason,
            "version": expected_version,
        }
        signature = canonical(command)
        existing = self.repo.command(actor_id, key)
        if existing:
            if existing[0] != signature:
                raise RuntimeError("IDEMPOTENCY_KEY_CONFLICT")
            return existing[1]  # type: ignore[return-value]
        history = instance.transition(
            template.definition, action, actor_id, reason, expected_version
        )
        self.repo.save_instance(instance)
        self.repo.save_command(actor_id, key, signature, instance)
        self.repo.append_outbox(
            {
                "event_type": "Workflow.Transitioned",
                "event_version": 1,
                "project_id": instance.project_id,
                "data": {
                    "instance_id": instance.id,
                    "from_state": history.from_state,
                    "to_state": history.to_state,
                    "action": action,
                    "instance_version": instance.version,
                    "reason_present": bool(reason),
                },
            }
        )
        return instance


def canonical(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
