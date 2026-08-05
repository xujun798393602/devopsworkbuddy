from unittest.mock import patch

import pytest

from project_service.config import Settings


def test_database_url_is_redacted_from_repr() -> None:
    settings = Settings(database_url="postgresql+psycopg://user:secret@db/service")
    assert "secret" not in repr(settings)


def test_production_requires_database_url() -> None:
    with (
        patch("project_service.config.getenv", side_effect={"APP_ENV": "production", "DATABASE_URL": "", "SERVICE_NAME": "project-service", "ALLOWED_ORIGINS": "http://localhost:5173"}.get),
        pytest.raises(RuntimeError, match="DATABASE_URL"),
    ):
        Settings.from_env()


def test_test_configuration_can_be_explicit() -> None:
    settings = Settings(environment="test", database_url="postgresql+psycopg://test:test@db/test")
    assert settings.environment == "test"
