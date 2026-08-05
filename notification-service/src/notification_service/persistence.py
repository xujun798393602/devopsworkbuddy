"""SQLAlchemy persistence for the notification private database."""

import os
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from notification_service.notifications.models import (
    Delivery,
    Notification,
    NotificationPreference,
)
from notification_service.notifications.service import NotificationService


class Base(DeclarativeBase):
    """Declarative metadata root for the notification private database."""


class NotificationRow(Base):
    """Persisted immutable notification content."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationDeliveryRow(Base):
    """Recipient-isolated delivery with optimistic versioning."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "recipient_id",
            "source_event_id",
            "template_key",
            name="uq_notification_delivery_dedup",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    notification_id: Mapped[str] = mapped_column(
        ForeignKey("notifications.id"), nullable=False
    )
    recipient_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class NotificationPreferenceRow(Base):
    """Persisted user preference with optimistic versioning."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    category: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Validated notification database configuration."""

    environment: str = "development"
    database_url: str = ""

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        """Load settings and fail closed outside explicit test mode."""
        value = cls(
            os.getenv("APP_ENV", "development").strip().lower(),
            os.getenv("DATABASE_URL", "").strip(),
        )
        if not value.database_url and value.environment != "test":
            raise RuntimeError("DATABASE_URL is required")
        return value


class SqlAlchemyNotificationUnitOfWork(NotificationService):
    """Request-scoped notification service and SQL transaction boundary."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self._load()

    def _load(self) -> None:
        for row in self.session.scalars(select(NotificationRow)):
            self.notifications[row.id] = Notification(
                row.id,
                row.source_event_id,
                row.template_key,
                row.category,
                row.title,
                row.body,
                row.target_url,
                row.severity,
                row.created_at,
            )
        for row in self.session.scalars(select(NotificationDeliveryRow)):
            delivery = Delivery(
                row.id,
                row.notification_id,
                row.recipient_id,
                row.source_event_id,
                row.template_key,
                row.status,
                row.read_at,
                row.version,
            )
            self.deliveries[row.id] = delivery
            self.dedup[
                (row.recipient_id, row.source_event_id, row.template_key)
            ] = row.id
        for row in self.session.scalars(select(NotificationPreferenceRow)):
            self.preferences[(row.user_id, row.category)] = NotificationPreference(
                row.user_id,
                row.category,
                row.enabled,
                row.locked,
                row.version,
            )

    def commit(self) -> None:
        """Persist content, deliveries, and preferences atomically."""
        try:
            for item in self.notifications.values():
                if self.session.get(NotificationRow, item.id) is None:
                    self.session.add(
                        NotificationRow(
                            id=item.id,
                            source_event_id=item.source_event_id,
                            template_key=item.template_key,
                            category=item.category,
                            title=item.title,
                            body=item.body,
                            target_url=item.target_url,
                            severity=item.severity,
                            created_at=item.created_at,
                        )
                    )
            for item in self.deliveries.values():
                row = self.session.get(NotificationDeliveryRow, item.id)
                if row is None:
                    self.session.add(
                        NotificationDeliveryRow(
                            id=item.id,
                            notification_id=item.notification_id,
                            recipient_id=item.recipient_id,
                            source_event_id=item.source_event_id,
                            template_key=item.template_key,
                            status=item.status,
                            read_at=item.read_at,
                            version=item.version,
                        )
                    )
                else:
                    if row.version > item.version:
                        raise RuntimeError("VERSION_CONFLICT")
                    row.status = item.status
                    row.read_at = item.read_at
                    row.version = item.version
            for item in self.preferences.values():
                identity = {"user_id": item.user_id, "category": item.category}
                row = self.session.get(NotificationPreferenceRow, identity)
                if row is None:
                    self.session.add(
                        NotificationPreferenceRow(
                            user_id=item.user_id,
                            category=item.category,
                            enabled=item.enabled,
                            locked=item.locked,
                            version=item.version,
                        )
                    )
                else:
                    if row.version > item.version:
                        raise RuntimeError("VERSION_CONFLICT")
                    row.enabled = item.enabled
                    row.locked = item.locked
                    row.version = item.version
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def rollback(self) -> None:
        """Rollback the active request transaction."""
        self.session.rollback()


class SqlAlchemyRuntime:
    """Own the notification engine and sessions."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        self.engine: Engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def unit_of_work(self) -> SqlAlchemyNotificationUnitOfWork:
        """Create one request-scoped unit of work."""
        return SqlAlchemyNotificationUnitOfWork(self.sessions())

    def ready(self) -> None:
        """Raise when the private database cannot serve queries."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
