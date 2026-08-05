"""Recipient-isolated notification Flask API."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from flask import Flask, Response, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from notification_service.notifications.models import NotificationPreference
from notification_service.notifications.service import NotificationService
from notification_service.persistence import (
    DatabaseSettings,
    SqlAlchemyNotificationUnitOfWork,
    SqlAlchemyRuntime,
)


class Committer(Protocol):
    """Transactional methods implemented by SQL notification units."""

    def commit(self) -> None:
        """Commit current changes."""

    def rollback(self) -> None:
        """Rollback current changes."""


def create_app(service: NotificationService | None = None) -> Flask:
    """Create the app with explicit memory injection or SQL production."""
    app = Flask(__name__)
    runtime: SqlAlchemyRuntime | None = None
    if service is None:
        settings = DatabaseSettings.from_env()
        runtime = SqlAlchemyRuntime(settings.database_url)
    app.extensions["notification_runtime"] = runtime
    app.extensions["notification_service"] = service

    def current_service() -> NotificationService:
        if service is not None:
            return service
        if "notification_uow" not in g:
            if runtime is None:
                raise RuntimeError("Notification SQL runtime is not configured")
            g.notification_uow = runtime.unit_of_work()
        return g.notification_uow

    def commit() -> None:
        unit = g.get("notification_uow")
        if unit is not None:
            unit.commit()

    @app.before_request
    def trace() -> None:
        g.trace_id = request.headers.get("X-Trace-Id", str(uuid4()))

    @app.teardown_request
    def close_session(error: BaseException | None) -> None:
        unit: SqlAlchemyNotificationUnitOfWork | None = g.pop(
            "notification_uow", None
        )
        if unit is not None:
            if error is not None:
                unit.rollback()
            unit.session.close()

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok", "service": "notification-service"})

    @app.get("/ready")
    def ready():
        if runtime is None:
            return jsonify({"status": "ready", "adapter": "memory"})
        try:
            runtime.ready()
        except SQLAlchemyError:
            return jsonify({"status": "not_ready"}), 503
        return jsonify({"status": "ready", "adapter": "sqlalchemy"})

    @app.post("/internal/api/v1/notifications")
    def consume():
        scopes = set(request.headers.get("X-Service-Scopes", "").split())
        if "notification:ingest" not in scopes:
            return problem(403, "INGEST_FORBIDDEN", "Notification ingest forbidden")
        try:
            delivery = current_service().consume(request.get_json(silent=True) or {})
            commit()
        except (KeyError, TypeError, ValueError) as error:
            return problem(422, str(error), str(error))
        except SQLAlchemyError:
            return problem(503, "DATABASE_UNAVAILABLE", "Notification database unavailable")
        return success(None if delivery is None else delivery_data(delivery)), 201

    @app.get("/api/v1/me/notifications")
    def list_notifications() -> Response:
        notifications = current_service()
        items = [
            delivery_data(item)
            for item in notifications.deliveries.values()
            if item.recipient_id == actor()
        ]
        return success(items)

    @app.get("/api/v1/me/notifications/unread-count")
    def unread_count() -> Response:
        return success({"count": current_service().unread_count(actor())})

    @app.get("/api/v1/me/notifications/<delivery_id>")
    def detail(delivery_id: str):
        notifications = current_service()
        try:
            delivery = notifications.get(actor(), delivery_id)
        except LookupError:
            return problem(404, "NOT_FOUND", "Notification not found")
        fact = notifications.notifications[delivery.notification_id]
        return success(
            {**delivery_data(delivery), "notification": notification_data(fact)}
        )

    def set_read_state(delivery_id: str, read: bool):
        notifications = current_service()
        try:
            delivery = notifications.get(actor(), delivery_id)
            if read:
                delivery.mark_read(datetime.now(UTC))
            else:
                delivery.mark_unread()
            commit()
        except LookupError:
            return problem(404, "NOT_FOUND", "Notification not found")
        except SQLAlchemyError:
            return problem(503, "DATABASE_UNAVAILABLE", "Notification database unavailable")
        return success(delivery_data(delivery))

    @app.put("/api/v1/me/notifications/<delivery_id>/read")
    def mark_read(delivery_id: str):
        return set_read_state(delivery_id, True)

    @app.put("/api/v1/me/notifications/<delivery_id>/unread")
    def mark_unread(delivery_id: str):
        return set_read_state(delivery_id, False)

    @app.put("/api/v1/me/notifications/read-all")
    def read_all() -> Response:
        notifications = current_service()
        now = datetime.now(UTC)
        for delivery in notifications.deliveries.values():
            if delivery.recipient_id == actor() and delivery.status == "unread":
                delivery.mark_read(now)
        try:
            commit()
        except SQLAlchemyError:
            return problem(503, "DATABASE_UNAVAILABLE", "Notification database unavailable")
        return success({"count": notifications.unread_count(actor())})

    @app.get("/api/v1/me/notification-preferences")
    def list_preferences() -> Response:
        values = [
            preference_data(item)
            for item in current_service().preferences.values()
            if item.user_id == actor()
        ]
        return success(values)

    @app.put("/api/v1/me/notification-preferences")
    def update_preferences():
        notifications = current_service()
        body = request.get_json(silent=True) or {}
        category = str(body.get("category", ""))
        enabled = bool(body.get("enabled", True))
        if not category:
            return problem(422, "CATEGORY_REQUIRED", "category is required")
        key = (actor(), category)
        preference = notifications.preferences.get(key)
        if preference is None:
            preference = NotificationPreference(
                actor(), category, True, category == "security"
            )
            notifications.preferences[key] = preference
        try:
            preference.set_enabled(enabled, int(body.get("version", preference.version)))
            commit()
        except RuntimeError as error:
            return problem(412, str(error), str(error))
        except ValueError as error:
            return problem(422, str(error), str(error))
        except SQLAlchemyError:
            return problem(503, "DATABASE_UNAVAILABLE", "Notification database unavailable")
        return success(preference_data(preference))

    return app


def actor() -> str:
    """Return the authenticated actor propagated by the gateway."""
    return request.headers.get("X-Actor-Id", "")


def delivery_data(item) -> dict[str, object]:
    """Serialize one delivery."""
    return {
        "id": item.id,
        "notification_id": item.notification_id,
        "recipient_id": item.recipient_id,
        "status": item.status,
        "read_at": item.read_at.isoformat() if item.read_at else None,
        "version": item.version,
    }


def notification_data(item) -> dict[str, object]:
    """Serialize immutable notification content."""
    return {
        "id": item.id,
        "title": item.title,
        "body": item.body,
        "target_url": item.target_url,
        "category": item.category,
        "severity": item.severity,
        "created_at": item.created_at.isoformat(),
    }


def preference_data(item) -> dict[str, object]:
    """Serialize one preference."""
    return {
        "category": item.category,
        "enabled": item.enabled,
        "locked": item.locked,
        "version": item.version,
    }


def success(data: object) -> Response:
    """Build a successful API envelope."""
    return jsonify({"data": data, "meta": {"trace_id": g.trace_id}})


def problem(status: int, code: str, detail: str):
    """Build an RFC 7807-compatible error response."""
    return (
        jsonify(
            {
                "type": "about:blank",
                "title": code,
                "status": status,
                "detail": detail,
                "error_code": code,
                "trace_id": g.trace_id,
            }
        ),
        status,
        {"Content-Type": "application/problem+json"},
    )
