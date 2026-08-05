import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration
DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def test_migration_owner_backfill_and_constraints() -> None:
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured; PostgreSQL migration tests not executed")
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            )
        }
        assert {
            "project_memberships",
            "release_versions",
            "iterations",
            "tasks",
            "worklogs",
            "audit_records",
            "outbox_events",
        } <= tables
        missing = connection.scalar(
            text(
                "SELECT count(*) FROM projects p WHERE NOT EXISTS (SELECT 1 FROM project_memberships m WHERE m.project_id=p.id AND m.status='active' AND m.role='owner')"
            )
        )
        assert missing == 0
    engine.dispose()
