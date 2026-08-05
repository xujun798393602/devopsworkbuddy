from datetime import UTC, datetime
from uuid import uuid4

from notification_service.notifications.models import (
    Delivery,
    Notification,
    NotificationPreference,
)
from notification_service.notifications.templates import (
    TemplateRenderer,
    validate_target_url,
)


class NotificationService:
    def __init__(self) -> None:
        self.renderer = TemplateRenderer()
        self.notifications: dict[str, Notification] = {}
        self.deliveries: dict[str, Delivery] = {}
        self.dedup: dict[tuple[str, str, str], str] = {}
        self.preferences: dict[tuple[str, str], NotificationPreference] = {}

    def consume(self, event: dict[str, object]) -> Delivery | None:
        recipient = str(event["recipient_id"])
        category = str(event["category"])
        key = (recipient, category)
        preference = self.preferences.setdefault(
            key,
            NotificationPreference(recipient, category, True, category == "security"),
        )
        if not preference.enabled:
            return None
        dedup = (
            recipient,
            str(event["source_event_id"]),
            str(event["template_key"]),
        )
        if dedup in self.dedup:
            return self.deliveries[self.dedup[dedup]]
        title, body = self.renderer.render(
            str(event["template_key"]), dict(event["variables"])
        )
        notification = Notification(
            str(uuid4()),
            dedup[1],
            dedup[2],
            category,
            title,
            body,
            validate_target_url(event.get("target_url")),
            str(event.get("severity", "info")),
            datetime.now(UTC),
        )
        delivery = Delivery(
            str(uuid4()), notification.id, recipient, dedup[1], dedup[2]
        )
        self.notifications[notification.id] = notification
        self.deliveries[delivery.id] = delivery
        self.dedup[dedup] = delivery.id
        return delivery

    def get(self, user_id: str, delivery_id: str) -> Delivery:
        item = self.deliveries.get(delivery_id)
        if item is None or item.recipient_id != user_id:
            raise LookupError("NOT_FOUND")
        return item

    def unread_count(self, user_id: str) -> int:
        return sum(
            item.recipient_id == user_id and item.status == "unread"
            for item in self.deliveries.values()
        )
