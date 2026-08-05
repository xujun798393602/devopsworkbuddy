"""TP runtime configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    """Settings requiring private PostgreSQL in production."""

    app_env: str = "development"
    database_url: str = ""

    @classmethod
    def from_env(cls) -> Config:
        """Load settings and fail closed for production deployments."""
        value = cls(
            os.getenv("APP_ENV", "development").strip().lower(),
            os.getenv("DATABASE_URL", "").strip(),
        )
        if value.app_env in {"production", "container"} and not value.database_url:
            raise RuntimeError("DATABASE_URL is required in production")
        return value
