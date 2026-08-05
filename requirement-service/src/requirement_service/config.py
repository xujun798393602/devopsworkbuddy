"""Validated environment configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime settings with production fail-closed validation."""

    service_name: str = "requirement-service"
    port: int = 18110
    database_url: str = ""
    app_env: str = "development"

    @classmethod
    def from_env(cls) -> Config:
        """Load configuration and require a private database in production."""
        config = cls(
            database_url=os.getenv("DATABASE_URL", "").strip(),
            app_env=os.getenv("APP_ENV", "development").strip().lower(),
        )
        if config.app_env in {"production", "container"} and not config.database_url:
            raise RuntimeError("DATABASE_URL is required in production")
        return config
