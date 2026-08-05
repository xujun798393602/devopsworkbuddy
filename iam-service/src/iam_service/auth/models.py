"""IAM domain aggregates without cross-service ORM dependencies."""
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass(slots=True)
class User:
    id: str
    username: str
    display_name: str
    status: UserStatus = UserStatus.ACTIVE
    permissions: tuple[str, ...] = field(default_factory=tuple)
    version: int = 1


@dataclass(slots=True)
class Session:
    id: str
    user_id: str
    family_id: str
    current_refresh_hash: str
    previous_refresh_hash: str | None
    expires_at: datetime
    idle_expires_at: datetime
    auth_method: str = "local_dev"
    status: SessionStatus = SessionStatus.ACTIVE
    revoked_reason: str | None = None
    version: int = 1

    @classmethod
    def create(cls, user_id: str, refresh_hash: str, ttl: int, auth_method: str = "local_dev") -> "Session":
        now = datetime.now(UTC)
        return cls(str(uuid4()), user_id, str(uuid4()), refresh_hash, None, now + timedelta(seconds=ttl), now + timedelta(hours=2), auth_method)

    def rotate(self, new_hash: str) -> None:
        if self.status != SessionStatus.ACTIVE:
            raise ValueError("Session is not active")
        self.previous_refresh_hash = self.current_refresh_hash
        self.current_refresh_hash = new_hash
        self.version += 1

    def revoke(self, reason: str) -> None:
        self.status = SessionStatus.REVOKED
        self.revoked_reason = reason
        self.version += 1
