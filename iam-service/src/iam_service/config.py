"""IAM configuration and production safety validation."""
import os
from dataclasses import dataclass

PRODUCTION_LIKE_ENVIRONMENTS = frozenset({"production", "container"})
"""Environments that must never reach the in-memory repository fallback.

The other six domain services use exactly this set to arm their persistence
fail-fast, so IAM stays consistent with them: a missing ``DATABASE_URL`` is a
start-up failure rather than a silent downgrade that still reports healthy.
"""

DEVELOPMENT_SECRET_PREFIX = "development-"
"""Marker identifying the in-repository placeholder secrets."""

DEVELOPMENT_JWT_PROVIDER = "development-hs256"
"""The only JWT provider this service currently implements.

``iam_service.auth.tokens.TokenService`` signs and verifies with a fixed
``HS256`` allowlist; no asymmetric signer exists yet. The ``production``
profile therefore demands a provider that is not implemented, which is a
deliberate, documented refusal to call the platform production ready -- not a
value that may be satisfied by relabelling the environment.
"""


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str = "development"
    service_name: str = "iam-service"
    local_dev_auth_enabled: bool = True
    jwt_issuer: str = "https://iam.local"
    jwt_audience: str = "platform-api"
    jwt_signing_key: str = "development-only-signing-key-at-least-32-bytes"
    refresh_pepper: str = "development-only-refresh-pepper"
    access_ttl: int = 600
    refresh_ttl: int = 28800
    jwt_provider: str = DEVELOPMENT_JWT_PROVIDER
    break_glass_enabled: bool = True
    break_glass_allowed_cidrs: tuple[str, ...] = ("127.0.0.0/8", "::1/128")
    database_url: str = ""
    allow_explicit_dev_auth: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        value = cls(
            app_env=os.getenv("APP_ENV", "development").strip().lower(),
            local_dev_auth_enabled=_bool("LOCAL_DEV_AUTH_ENABLED", True),
            jwt_issuer=os.getenv("JWT_ISSUER", "https://iam.local"),
            jwt_audience=os.getenv("JWT_AUDIENCE", "platform-api"),
            jwt_signing_key=os.getenv(
                "JWT_SIGNING_KEY",
                "development-only-signing-key-at-least-32-bytes",
            ),
            refresh_pepper=os.getenv(
                "REFRESH_TOKEN_PEPPER", "development-only-refresh-pepper"
            ),
            jwt_provider=os.getenv("JWT_PROVIDER", DEVELOPMENT_JWT_PROVIDER)
            .strip()
            .lower(),
            break_glass_enabled=_bool("BREAK_GLASS_ENABLED", True),
            database_url=os.getenv("DATABASE_URL", "").strip(),
            allow_explicit_dev_auth=_bool("ALLOW_EXPLICIT_DEV_AUTH", False),
        )
        value.validate()
        return value

    def validate(self) -> None:
        """Fail closed for every environment that must not run on memory.

        ``container`` is the integration profile: it shares the persistence
        contract of ``production`` but still authenticates through the local
        development provider, because no external identity provider exists
        yet. That downgrade is permitted only when it is stated explicitly via
        ``ALLOW_EXPLICIT_DEV_AUTH``, mirroring the ``ALLOW_EXPLICIT_MOCK_CAPABILITY``
        contract the other services use for their mock adapters. ``production``
        keeps the full posture unchanged.
        """
        if self.app_env not in PRODUCTION_LIKE_ENVIRONMENTS:
            return
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required in production")
        if self.app_env == "container":
            self._validate_container()
            return
        self._validate_production()

    def _validate_container(self) -> None:
        """Allow the acknowledged development login path, nothing implicit."""
        if self.local_dev_auth_enabled and not self.allow_explicit_dev_auth:
            raise RuntimeError(
                "LOCAL_DEV_AUTH_ENABLED requires an explicit "
                "ALLOW_EXPLICIT_DEV_AUTH acknowledgement outside development"
            )

    def _validate_production(self) -> None:
        """Enforce the unchanged, fully external production posture."""
        if self.local_dev_auth_enabled:
            raise RuntimeError("LOCAL_DEV_AUTH_ENABLED is forbidden in production")
        if self.jwt_signing_key.startswith(
            DEVELOPMENT_SECRET_PREFIX
        ) or self.refresh_pepper.startswith(DEVELOPMENT_SECRET_PREFIX):
            raise RuntimeError("Production secrets must be externally supplied")
        if self.jwt_provider == DEVELOPMENT_JWT_PROVIDER:
            raise RuntimeError("Production requires an asymmetric JWT provider")
        if self.break_glass_enabled:
            raise RuntimeError("Production break-glass requires an external TOTP provider")
