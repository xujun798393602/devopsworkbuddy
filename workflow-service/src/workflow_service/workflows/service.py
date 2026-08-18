"""Workflow application service with authorization, idempotency, and outbox."""
import hashlib
import json
from uuid import uuid4

from workflow_service.integrations.project_authorization import ProjectAuthorizationPort
from workflow_service.workflows.models import WorkflowInstance
from workflow_service.workflows.repository import (
    PORTAL_APPROVAL_LIMIT_DEFAULT,
    PortalApprovalSnapshot,
    PortalRepository,
    WorkflowRepository,
)


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


def _portal_scope(project_ids: tuple[str, ...]) -> tuple[str, ...]:
    """De-duplicate while preserving order; never mutate the caller's tuple."""
    return tuple(dict.fromkeys(project_ids))


def _portal_approval_item(snapshot: PortalApprovalSnapshot) -> dict[str, object]:
    """Serialize a pending-approval projection for the dashboard contract."""
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "business_object_type": snapshot.business_object_type,
        "business_object_id": snapshot.business_object_id,
        "current_state": snapshot.current_state,
        "started_at": snapshot.started_at,
    }


class WorkflowPortalService:
    """Read-only dashboard projection for workflow pending approvals."""

    def __init__(self, repository: PortalRepository) -> None:
        self.repository = repository

    def summary(
        self,
        project_ids: tuple[str, ...],
        actor_id: str | None = None,
        *,
        cross_project: bool = False,
        limit: int = PORTAL_APPROVAL_LIMIT_DEFAULT,
    ) -> dict[str, object]:
        """Return the count and a length-bounded list of pending approvals.

        ``actor_id`` is accepted for signature parity with the other portal
        services; the gateway already scopes ``project_ids`` to the caller's
        projects, so no extra actor filtering is required here.
        """
        snapshot_scope = _portal_scope(project_ids)
        snapshots = self.repository.pending_approvals(snapshot_scope, cross_project)
        items = [_portal_approval_item(snapshot) for snapshot in snapshots[:limit]]
        return {"count": len(snapshots), "items": items}
