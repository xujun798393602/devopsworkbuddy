"""Replaceable identity provider contracts."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    subject: str
    username: str
    display_name: str


class IdentityProviderAdapter(Protocol):
    def authenticate_dev(self, username: str) -> ExternalIdentity: ...


class LocalDevProvider:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def authenticate_dev(self, username: str) -> ExternalIdentity:
        normalized = username.strip().lower()
        if not self.enabled or normalized not in {"developer", "auditor", "workflow-admin"}:
            raise PermissionError("Authentication failed")
        return ExternalIdentity(f"local:{normalized}", normalized, normalized.replace("-", " ").title())
