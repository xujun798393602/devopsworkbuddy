"""Environment-backed TD service configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    """Validated runtime configuration."""

    environment: str = "development"
    database_url: str = ""

    @classmethod
    def from_env(cls) -> Config:
        """Load settings and fail closed for production database wiring."""
        settings = cls(
            environment=os.getenv("APP_ENV", "development").strip().casefold(),
            database_url=os.getenv("DATABASE_URL", "").strip(),
        )
        if settings.environment in {"production", "container"} and not settings.database_url:
            raise RuntimeError("DATABASE_URL is required in production")
        return settings
