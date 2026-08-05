"""Fail-closed project authorization port."""
from typing import Protocol


class ProjectAuthorizationPort(Protocol):
    def check(self, actor_id: str, project_id: str, action: str, resource: dict[str, str]) -> bool: ...

class ControlledAuthorizer:
    """Explicit grants for local golden-chain tests; not an integration substitute."""
    def __init__(self, grants: set[tuple[str, str, str]] | None = None) -> None:
        self.grants = grants or {("development-user", "demo-project", "workflow.start"), ("development-user", "demo-project", "workflow.transition"), ("development-user", "demo-project", "workflow.read")}
    def check(self, actor_id: str, project_id: str, action: str, resource: dict[str, str]) -> bool:
        return (actor_id, project_id, action) in self.grants
