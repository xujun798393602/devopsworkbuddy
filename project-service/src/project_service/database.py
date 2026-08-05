from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from project_service.config import Settings


class Database:
    """Owns the SQLAlchemy engine and session factory."""

    def __init__(self, settings: Settings) -> None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is required")
        options: dict[str, object] = {"pool_pre_ping": True}
        if not settings.database_url.startswith("sqlite"):
            timeout_seconds = max(1, int(settings.readiness_timeout))
            options.update(
                pool_size=settings.database_pool_size,
                pool_timeout=settings.database_pool_timeout,
                isolation_level="READ COMMITTED",
                connect_args={
                    "connect_timeout": timeout_seconds,
                    "options": f"-c statement_timeout={timeout_seconds * 1000}",
                },
            )
        self.engine: Engine = create_engine(settings.database_url, **options)
        self.sessions: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False
        )

    def ping(self) -> bool:
        """Execute a driver-bounded, short-lived connectivity check."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self) -> None:
        """Close pooled database connections."""
        self.engine.dispose()
