"""Boot contract for the IAM configuration profiles.

Regression guard for the task51 fix8 start-up abort: ``compose.integration.yaml``
arms every service with ``APP_ENV=container`` so a missing ``DATABASE_URL`` can
no longer downgrade to memory. IAM, however, folded the entire production
authentication posture into the same branch while ``jwt_provider`` and
``break_glass_enabled`` were never read from the environment. Their frozen
dataclass defaults made the branch unsatisfiable, so ``Settings.from_env()``
raised ``Production requires an asymmetric JWT provider`` no matter what an
operator injected -- IAM could not start in the profile at all.
"""

import pytest

from iam_service.config import DEVELOPMENT_JWT_PROVIDER, Settings

CONTAINER_ENVIRONMENT = {
    "APP_ENV": "container",
    "DATABASE_URL": "postgresql+psycopg://wkdevops_admin@platform-postgres:5432/wkdevops_iam",
    "ALLOW_EXPLICIT_DEV_AUTH": "true",
}


def _apply(monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]) -> None:
    """Install exactly the given process environment for the IAM settings."""
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "ALLOW_EXPLICIT_DEV_AUTH",
        "LOCAL_DEV_AUTH_ENABLED",
        "JWT_PROVIDER",
        "BREAK_GLASS_ENABLED",
        "JWT_SIGNING_KEY",
        "REFRESH_TOKEN_PEPPER",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)


def test_container_profile_boots_with_an_acknowledged_dev_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The integration profile must actually be startable."""
    _apply(monkeypatch, CONTAINER_ENVIRONMENT)
    settings = Settings.from_env()
    assert settings.app_env == "container"
    assert settings.database_url.endswith("/wkdevops_iam")
    assert settings.local_dev_auth_enabled is True
    assert settings.allow_explicit_dev_auth is True


def test_container_profile_fails_closed_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing DSN must abort start-up instead of selecting memory."""
    environment = dict(CONTAINER_ENVIRONMENT)
    del environment["DATABASE_URL"]
    _apply(monkeypatch, environment)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        Settings.from_env()


def test_container_profile_rejects_an_unacknowledged_dev_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The development login path must never be inherited from a default."""
    environment = dict(CONTAINER_ENVIRONMENT)
    del environment["ALLOW_EXPLICIT_DEV_AUTH"]
    _apply(monkeypatch, environment)
    with pytest.raises(RuntimeError, match="ALLOW_EXPLICIT_DEV_AUTH"):
        Settings.from_env()


def test_container_profile_accepts_a_disabled_dev_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning the development provider off needs no acknowledgement."""
    environment = dict(CONTAINER_ENVIRONMENT)
    del environment["ALLOW_EXPLICIT_DEV_AUTH"]
    environment["LOCAL_DEV_AUTH_ENABLED"] = "false"
    _apply(monkeypatch, environment)
    assert Settings.from_env().local_dev_auth_enabled is False


def test_production_posture_is_reachable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every production knob must be injectable, not frozen in the dataclass.

    ``jwt_provider`` and ``break_glass_enabled`` used to be unreadable from the
    environment, which made the production branch permanently unsatisfiable and
    hid the fact that the checks were dead code.
    """
    _apply(
        monkeypatch,
        {
            "APP_ENV": "production",
            "DATABASE_URL": "postgresql+psycopg://wkdevops_admin@platform-postgres:5432/wkdevops_iam",
            "LOCAL_DEV_AUTH_ENABLED": "false",
            "JWT_SIGNING_KEY": "externally-supplied-signing-key-at-least-32b",
            "REFRESH_TOKEN_PEPPER": "externally-supplied-refresh-pepper",
            "JWT_PROVIDER": "external-rs256",
            "BREAK_GLASS_ENABLED": "false",
        },
    )
    settings = Settings.from_env()
    assert settings.app_env == "production"
    assert settings.jwt_provider == "external-rs256"
    assert settings.break_glass_enabled is False


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"LOCAL_DEV_AUTH_ENABLED": "true"}, "LOCAL_DEV_AUTH_ENABLED is forbidden"),
        ({"JWT_SIGNING_KEY": "development-only-key"}, "externally supplied"),
        ({"REFRESH_TOKEN_PEPPER": "development-only-pepper"}, "externally supplied"),
        ({"JWT_PROVIDER": DEVELOPMENT_JWT_PROVIDER}, "asymmetric JWT provider"),
        ({"BREAK_GLASS_ENABLED": "true"}, "break-glass"),
    ],
)
def test_production_posture_stays_strict(
    monkeypatch: pytest.MonkeyPatch, override: dict[str, str], message: str
) -> None:
    """Splitting the container branch must not relax a single production rule."""
    environment = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://wkdevops_admin@platform-postgres:5432/wkdevops_iam",
        "LOCAL_DEV_AUTH_ENABLED": "false",
        "JWT_SIGNING_KEY": "externally-supplied-signing-key-at-least-32b",
        "REFRESH_TOKEN_PEPPER": "externally-supplied-refresh-pepper",
        "JWT_PROVIDER": "external-rs256",
        "BREAK_GLASS_ENABLED": "false",
    }
    environment.update(override)
    _apply(monkeypatch, environment)
    with pytest.raises(RuntimeError, match=message):
        Settings.from_env()


def test_development_profile_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local development keeps working with no environment at all."""
    _apply(monkeypatch, {})
    settings = Settings.from_env()
    assert settings.app_env == "development"
    assert settings.database_url == ""
    assert settings.local_dev_auth_enabled is True
