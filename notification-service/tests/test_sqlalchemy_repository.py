"""SQL notification persistence and production assembly tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from notification_service.app import create_app
from notification_service.persistence import (
    Base,
    DatabaseSettings,
    NotificationDeliveryRow,
    NotificationPreferenceRow,
    NotificationRow,
    SqlAlchemyNotificationUnitOfWork,
)


def event() -> dict[str, object]:
    """Build a supported workflow notification event."""
    return {
        "recipient_id": "user-1",
        "source_event_id": "event-1",
        "template_key": "workflow.started",
        "category": "workflow",
        "variables": {"instance_id": "one"},
        "target_url": "/app/workflows/one",
    }


def test_sql_uow_round_trip_dedup_read_state_and_preference() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    first = SqlAlchemyNotificationUnitOfWork(sessions())
    delivery = first.consume(event())
    assert delivery is not None
    first.preferences[("user-1", "workflow")].set_enabled(False, 1)
    delivery.mark_read(delivery.read_at or first.notifications[delivery.notification_id].created_at)
    first.commit()
    first.session.close()

    second = SqlAlchemyNotificationUnitOfWork(sessions())
    loaded = second.deliveries[delivery.id]
    assert second.consume(event()) is None
    assert loaded.status == "read"
    assert second.preferences[("user-1", "workflow")].enabled is False
    assert second.session.query(NotificationRow).count() == 1
    assert second.session.query(NotificationDeliveryRow).count() == 1
    assert second.session.query(NotificationPreferenceRow).count() == 1
    second.session.close()


def test_http_state_persists_across_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    app = create_app()
    runtime = app.extensions["notification_runtime"]
    Base.metadata.create_all(runtime.engine)
    client = app.test_client()
    response = client.post(
        "/internal/api/v1/notifications",
        json=event(),
        headers={"X-Service-Scopes": "notification:ingest"},
    )
    delivery_id = response.get_json()["data"]["id"]
    marked = client.put(
        f"/api/v1/me/notifications/{delivery_id}/read",
        headers={"X-Actor-Id": "user-1"},
    )
    assert marked.status_code == 200
    assert client.get(
        "/api/v1/me/notifications/unread-count",
        headers={"X-Actor-Id": "user-1"},
    ).get_json()["data"]["count"] == 0


def test_production_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        DatabaseSettings.from_env()
