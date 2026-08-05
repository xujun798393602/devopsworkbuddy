"""Database boundary.

Production deployments configure a private PostgreSQL URL; domain tests use the explicit
MemoryUnitOfWork adapter and never share another service database.
"""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def build_engine(database_url: str) -> Engine:
    """Build a pool-pre-ping SQLAlchemy engine for this service only."""
    return create_engine(database_url, pool_pre_ping=True)
