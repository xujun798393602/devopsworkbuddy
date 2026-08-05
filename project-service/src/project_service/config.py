from dataclasses import dataclass, field
from os import getenv


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime configuration; secrets are excluded from repr."""

    environment: str = "development"
    service_name: str = "project-service"
    allowed_origins: tuple[str, ...] = ("http://localhost:5173",)
    database_url: str = field(default="", repr=False)
    database_pool_size: int = 5
    database_pool_timeout: float = 10.0
    readiness_timeout: float = 2.0
    internal_service_token: str = field(default="development-internal-token", repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        environment = getenv("APP_ENV", "development").strip()
        service_name = getenv("SERVICE_NAME", "project-service").strip()
        origins = tuple(
            value.strip()
            for value in getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
            if value.strip()
        )
        database_url = getenv("DATABASE_URL", "").strip()
        internal_service_token = getenv(
            "INTERNAL_SERVICE_TOKEN", "development-internal-token"
        ).strip()
        if not environment or not service_name or not origins or not internal_service_token:
            raise RuntimeError("APP_ENV, SERVICE_NAME, and ALLOWED_ORIGINS must not be empty")
        if environment in {"production", "container"} and not database_url:
            raise RuntimeError("DATABASE_URL is required in container and production environments")
        if environment == "production" and "*" in origins:
            raise RuntimeError("Wildcard CORS origin is forbidden in production")
        if environment in {"production", "container"} and internal_service_token.startswith(
            "development-"
        ):
            raise RuntimeError("INTERNAL_SERVICE_TOKEN must be externally supplied")
        return cls(
            environment=environment,
            service_name=service_name,
            allowed_origins=origins,
            database_url=database_url,
            database_pool_size=_positive_int("DATABASE_POOL_SIZE", 5),
            database_pool_timeout=_positive_float("DATABASE_POOL_TIMEOUT", 10.0),
            readiness_timeout=_positive_float("READINESS_TIMEOUT", 2.0),
            internal_service_token=internal_service_token,
        )


def _positive_int(name: str, default: int) -> int:
    value = int(getenv(name, str(default)))
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(getenv(name, str(default)))
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value
