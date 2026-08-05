from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Notification:
    id: str
    source_event_id: str
    template_key: str
    category: str
    title: str
    body: str
    target_url: str | None
    severity: str
    created_at: datetime


@dataclass(slots=True)
class Delivery:
    id: str
    notification_id: str
    recipient_id: str
    source_event_id: str
    template_key: str
    status: str = "unread"
    read_at: datetime | None = None
    version: int = 1

    def mark_read(self, now: datetime) -> None:
        self.status = "read"
        self.read_at = now
        self.version += 1

    def mark_unread(self) -> None:
        self.status = "unread"
        self.read_at = None
        self.version += 1


@dataclass(slots=True)
class NotificationPreference:
    user_id: str
    category: str
    enabled: bool = True
    locked: bool = False
    version: int = 1

    def set_enabled(self, value: bool, version: int) -> None:
        if version != self.version:
            raise RuntimeError("VERSION_CONFLICT")
        if self.locked and not value:
            raise ValueError("SECURITY_PREFERENCE_LOCKED")
        self.enabled = value
        self.version += 1
