#!/usr/bin/env python3
"""Run the fixed project-service PostgreSQL integration gate without exposing secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final
from urllib.parse import quote

SECRET_FILE: Final = Path("/project/devops-platform/shared/secrets/postgres-debug.env")
RUNTIME_CONFIG_FILE: Final = Path(__file__).resolve().parents[1] / "config" / "test-runtime.json"
ALLOWED_RUNTIME_ROOT: Final = Path("/project/devops-platform/shared/test-runtimes")
DATABASE_HOST: Final = "127.0.0.1"
DATABASE_PORT: Final = 25432
PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
ALLOWED_TESTS: Final = (
    "tests/test_postgres_integration.py",
    "tests/test_collaboration_postgres.py",
)
REQUIRED_KEYS: Final = frozenset({"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"})
SAFE_VALUE_PATTERN: Final = re.compile(r"^[^\x00\r\n]+$")
DSN_PATTERN: Final = re.compile(
    r"(?i)(?:postgres(?:ql)?(?:\+psycopg)?://)[^\s'\"<>]+"
)
PASSWORD_FIELD_PATTERN: Final = re.compile(
    r"(?i)(password\s*[=:]\s*)[^\s,;]+"
)


class SecureTestError(RuntimeError):
    """A safe-to-display failure raised before the test process starts."""


def parse_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    """Parse the only supported optional test enumeration flag."""
    parser = argparse.ArgumentParser(
        description="Run the fixed project-service PostgreSQL integration gate.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Safely enumerate the fixed integration tests without executing them.",
    )
    return parser.parse_args(arguments)


def read_secret_file(path: Path) -> dict[str, str]:
    """Read a root-owned mode-600 env file as data, never as shell code."""
    try:
        metadata = path.stat()
    except OSError as error:
        raise SecureTestError("PostgreSQL test credentials are unavailable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise SecureTestError("PostgreSQL test credential permissions are unsafe")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SecureTestError("PostgreSQL test credential permissions are unsafe")
    if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
        raise SecureTestError("PostgreSQL test credential ownership is unsafe")

    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise SecureTestError("PostgreSQL test credentials are unreadable") from error
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in REQUIRED_KEYS or key in values:
            raise SecureTestError("PostgreSQL test credential format is invalid")
        if not value or not SAFE_VALUE_PATTERN.fullmatch(value):
            raise SecureTestError("PostgreSQL test credential format is invalid")
        values[key] = value
    if values.keys() != REQUIRED_KEYS:
        raise SecureTestError("PostgreSQL test credentials are incomplete")
    return values


def build_database_url(credentials: Mapping[str, str]) -> str:
    """Build a psycopg URL with percent-encoded credentials."""
    user = quote(credentials["POSTGRES_USER"], safe="")
    password = quote(credentials["POSTGRES_PASSWORD"], safe="")
    database = quote(credentials["POSTGRES_DB"], safe="")
    return (
        f"postgresql+psycopg://{user}:{password}@{DATABASE_HOST}:"
        f"{DATABASE_PORT}/{database}"
    )


def sanitize_output(output: str, sensitive_values: Sequence[str]) -> str:
    """Remove known secret values and PostgreSQL URLs from process output."""
    sanitized = output
    for value in sorted((item for item in sensitive_values if item), key=len, reverse=True):
        sanitized = sanitized.replace(value, "[REDACTED]")
        encoded_value = quote(value, safe="")
        if len(encoded_value) >= 8:
            sanitized = sanitized.replace(encoded_value, "[REDACTED]")
    sanitized = DSN_PATTERN.sub("[REDACTED_DATABASE_URL]", sanitized)
    return PASSWORD_FIELD_PATTERN.sub(r"\1[REDACTED]", sanitized)


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest for a regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_test_runtime(config_file: Path = RUNTIME_CONFIG_FILE) -> Path:
    """Validate and return the configured immutable shared runtime interpreter."""
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        configured_path = config["runtime_path"]
        expected_manifest_hash = config["manifest_sha256"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise SecureTestError("configured test runtime is unavailable") from error
    if not isinstance(configured_path, str) or not isinstance(expected_manifest_hash, str):
        raise SecureTestError("configured test runtime is invalid")

    runtime = Path(configured_path)
    try:
        runtime_real = runtime.resolve(strict=True)
        allowed_root_real = ALLOWED_RUNTIME_ROOT.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SecureTestError("configured test runtime is unavailable") from error
    if runtime.is_symlink() or runtime_real.parent != allowed_root_real or not runtime_real.name:
        raise SecureTestError("configured test runtime is outside the allowed root")

    manifest_path = runtime_real / "runtime-manifest.json"
    python_path = runtime_real / "bin" / "python"
    pip_path = runtime_real / "bin" / "pip"
    pytest_path = runtime_real / "bin" / "pytest"
    try:
        objects = [allowed_root_real, runtime_real, *runtime_real.rglob("*")]
        for path in objects:
            metadata = path.lstat()
            is_symlink = stat.S_ISLNK(metadata.st_mode)
            if metadata.st_uid != 0 or (not is_symlink and stat.S_IMODE(metadata.st_mode) & 0o222):
                raise SecureTestError("configured test runtime ownership or permissions are unsafe")
            if is_symlink:
                path.resolve(strict=True).relative_to(runtime_real)
        if not all(path.is_file() for path in (python_path, pip_path, pytest_path)):
            raise SecureTestError("configured test runtime executables are unavailable")
        if sha256_file(manifest_path) != expected_manifest_hash:
            raise SecureTestError("configured test runtime manifest hash is invalid")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except SecureTestError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SecureTestError("configured test runtime validation failed") from error
    if manifest.get("runtime_path") != str(runtime_real) or manifest.get("schema_version") != 1:
        raise SecureTestError("configured test runtime manifest is invalid")

    probe_environment = {"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"}
    probe_commands = (
        [str(python_path), "-c", "import alembic, pip, psycopg, pytest, sqlalchemy"],
        [str(python_path), "-m", "pip", "--version"],
        [str(python_path), "-m", "pytest", "--version"],
    )
    for command in probe_commands:
        probe = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=probe_environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            raise SecureTestError("configured test runtime dependency check failed")
    return python_path


def fixed_test_command(collect_only: bool) -> list[str]:
    """Return the fixed pytest command using only the validated shared runtime."""
    command = [str(validate_test_runtime()), "-m", "pytest", *ALLOWED_TESTS, "-ra"]
    if collect_only:
        command.append("--collect-only")
    return command


def run(arguments: Sequence[str], secret_file: Path = SECRET_FILE) -> int:
    """Inject credentials into an isolated child environment and run the gate."""
    options = parse_arguments(arguments)
    credentials: dict[str, str] = {}
    child_environment: dict[str, str] = {}
    database_url = ""
    try:
        credentials = read_secret_file(secret_file)
        database_url = build_database_url(credentials)
        child_environment = os.environ.copy()
        child_environment["TEST_DATABASE_URL"] = database_url
        child_environment["DATABASE_URL"] = database_url
        completed = subprocess.run(
            fixed_test_command(options.collect_only),
            cwd=PROJECT_ROOT,
            env=child_environment,
            capture_output=True,
            text=True,
            check=False,
        )
        sensitive_values = [database_url, *credentials.values()]
        if completed.stdout:
            sys.stdout.write(sanitize_output(completed.stdout, sensitive_values))
        if completed.stderr:
            sys.stderr.write(sanitize_output(completed.stderr, sensitive_values))
        return completed.returncode
    except SecureTestError as error:
        sys.stderr.write(f"secure-postgres-test: {error}\n")
        return 78
    finally:
        child_environment.pop("TEST_DATABASE_URL", None)
        child_environment.pop("DATABASE_URL", None)
        credentials.clear()
        database_url = ""


def main() -> int:
    """Run the secure PostgreSQL test entry point."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
