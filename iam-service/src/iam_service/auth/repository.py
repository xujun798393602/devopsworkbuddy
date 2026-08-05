"""IAM repository ports and persistent adapters."""

from __future__ import annotations

from contextlib import AbstractContextManager
from threading import RLock
from typing import Protocol

from sqlalchemy import Engine, or_, select, update
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import sessionmaker

from iam_service.auth.models import Session, SessionStatus, User, UserStatus
from iam_service.persistence import SessionRow, UserRow


class IamRepository(Protocol):
    """Persistence contract consumed by the IAM application service."""

    def get_user_by_username(self, username: str) -> User | None: ...
    def get_user(self, user_id: str) -> User | None: ...
    def save_user(self, user: User) -> None: ...
    def find_session_hash(self, token_hash: str) -> Session | None: ...
    def save_session(self, session: Session) -> None: ...
    def revoke_family(self, family_id: str, reason: str) -> int: ...
    def check(self) -> None: ...


class InMemoryIamRepository:
    """Thread-safe adapter for unit tests and controlled local development."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.sessions: dict[str, Session] = {}
        self._lock = RLock()

    def get_user_by_username(self, username: str) -> User | None:
        return next(
            (user for user in self.users.values() if user.username == username), None
        )

    def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def save_user(self, user: User) -> None:
        with self._lock:
            self.users[user.id] = user

    def find_session_hash(self, token_hash: str) -> Session | None:
        return next(
            (
                item
                for item in self.sessions.values()
                if token_hash
                in {item.current_refresh_hash, item.previous_refresh_hash}
            ),
            None,
        )

    def save_session(self, session: Session) -> None:
        with self._lock:
            self.sessions[session.id] = session

    def revoke_family(self, family_id: str, reason: str) -> int:
        count = 0
        with self._lock:
            for session in self.sessions.values():
                if session.family_id == family_id and session.status == SessionStatus.ACTIVE:
                    session.revoke(reason)
                    count += 1
        return count

    def check(self) -> None:
        """In-memory storage is always available."""


class SqlAlchemyIamRepository:
    """PostgreSQL-compatible SQLAlchemy IAM repository."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = sessionmaker(
            bind=engine, expire_on_commit=False, class_=DatabaseSession
        )

    def _session(self) -> AbstractContextManager[DatabaseSession]:
        return self._session_factory.begin()

    def get_user_by_username(self, username: str) -> User | None:
        with self._session() as database:
            row = database.scalar(select(UserRow).where(UserRow.username == username))
            return _to_user(row)

    def get_user(self, user_id: str) -> User | None:
        with self._session() as database:
            return _to_user(database.get(UserRow, user_id))

    def save_user(self, user: User) -> None:
        with self._session() as database:
            database.merge(_user_row(user))

    def find_session_hash(self, token_hash: str) -> Session | None:
        with self._session() as database:
            row = database.scalar(
                select(SessionRow).where(
                    or_(
                        SessionRow.current_refresh_hash == token_hash,
                        SessionRow.previous_refresh_hash == token_hash,
                    )
                )
            )
            return _to_session(row)

    def save_session(self, session: Session) -> None:
        with self._session() as database:
            database.merge(_session_row(session))

    def revoke_family(self, family_id: str, reason: str) -> int:
        with self._session() as database:
            result = database.execute(
                update(SessionRow)
                .where(
                    SessionRow.family_id == family_id,
                    SessionRow.status == SessionStatus.ACTIVE.value,
                )
                .values(
                    status=SessionStatus.REVOKED.value,
                    revoked_reason=reason,
                    version=SessionRow.version + 1,
                )
            )
            return int(result.rowcount or 0)

    def check(self) -> None:
        """Fail if the private database cannot serve a simple query."""
        with self._session() as database:
            database.execute(select(1))


def _to_user(row: UserRow | None) -> User | None:
    if row is None:
        return None
    permissions = row.permissions if isinstance(row.permissions, list) else []
    return User(
        id=row.id,
        username=row.username,
        display_name=row.display_name,
        status=UserStatus(row.status),
        permissions=tuple(str(item) for item in permissions),
        version=row.version,
    )


def _user_row(user: User) -> UserRow:
    return UserRow(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        status=user.status.value,
        permissions=list(user.permissions),
        version=user.version,
    )


def _to_session(row: SessionRow | None) -> Session | None:
    if row is None:
        return None
    return Session(
        id=row.id,
        user_id=row.user_id,
        family_id=row.family_id,
        current_refresh_hash=row.current_refresh_hash,
        previous_refresh_hash=row.previous_refresh_hash,
        expires_at=row.expires_at,
        idle_expires_at=row.idle_expires_at,
        auth_method=row.auth_method,
        status=SessionStatus(row.status),
        revoked_reason=row.revoked_reason,
        version=row.version,
    )


def _session_row(session: Session) -> SessionRow:
    return SessionRow(
        id=session.id,
        user_id=session.user_id,
        family_id=session.family_id,
        current_refresh_hash=session.current_refresh_hash,
        previous_refresh_hash=session.previous_refresh_hash,
        expires_at=session.expires_at,
        idle_expires_at=session.idle_expires_at,
        auth_method=session.auth_method,
        status=session.status.value,
        revoked_reason=session.revoked_reason,
        version=session.version,
    )
