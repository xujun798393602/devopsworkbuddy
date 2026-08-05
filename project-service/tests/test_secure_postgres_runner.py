"""Security tests for the restricted PostgreSQL integration entry point."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
from urllib.parse import quote

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "run_postgres_integration.py"


def load_runner() -> ModuleType:
    """Load the executable script as a module for isolated unit tests."""
    specification = importlib.util.spec_from_file_location("secure_postgres_runner", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def write_secret(path: Path, password: str = "secret-value") -> None:
    """Create a representative mode-600 secret fixture."""
    path.write_text(
        f"POSTGRES_USER=test_user\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=test_db\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_missing_secret_fails_without_leaking_environment(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = load_runner()
    marker = "must-not-leak-from-parent-environment"
    previous_test_url = os.environ.get("TEST_DATABASE_URL")
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["TEST_DATABASE_URL"] = marker
    os.environ["DATABASE_URL"] = marker
    try:
        assert runner.run([], tmp_path / "missing.env") == 78
        assert os.environ["TEST_DATABASE_URL"] == marker
        assert os.environ["DATABASE_URL"] == marker
    finally:
        if previous_test_url is None:
            os.environ.pop("TEST_DATABASE_URL", None)
        else:
            os.environ["TEST_DATABASE_URL"] = previous_test_url
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
    output = capsys.readouterr()
    assert "credentials are unavailable" in output.err
    assert marker not in output.out + output.err


def test_fixed_whitelist_and_environment_cleanup(tmp_path: Path) -> None:
    runner = load_runner()
    secret_file = tmp_path / "postgres-debug.env"
    write_secret(secret_file)
    captured_environment: dict[str, str] = {}
    captured_command: list[str] = []

    def fake_run(command, *, cwd, env, capture_output, text, check):
        captured_command.extend(command)
        captured_environment.update(env)
        assert cwd == runner.PROJECT_ROOT
        assert capture_output is True and text is True and check is False
        return subprocess.CompletedProcess(command, 0, "2 passed\n", "")

    runtime_python = Path("/project/devops-platform/shared/test-runtimes/test/bin/python")
    with (
        patch.object(runner, "validate_test_runtime", return_value=runtime_python),
        patch.object(runner.subprocess, "run", side_effect=fake_run),
    ):
        assert runner.run([], secret_file) == 0

    assert captured_command == [
        str(runtime_python),
        "-m",
        "pytest",
        "tests/test_postgres_integration.py",
        "tests/test_collaboration_postgres.py",
        "-ra",
    ]
    assert captured_environment["TEST_DATABASE_URL"].startswith("postgresql+psycopg://")
    assert "TEST_DATABASE_URL" not in os.environ
    assert "DATABASE_URL" not in os.environ


def test_only_safe_enumeration_parameter_is_accepted() -> None:
    runner = load_runner()
    runtime_python = Path("/project/devops-platform/shared/test-runtimes/test/bin/python")
    with patch.object(runner, "validate_test_runtime", return_value=runtime_python):
        command = runner.fixed_test_command(True)
    assert command[0] == str(runtime_python)
    assert command[-1] == "--collect-only"
    with pytest.raises(SystemExit) as shell_parameter:
        runner.parse_arguments(["-c", "id"])
    with pytest.raises(SystemExit) as injected_test:
        runner.parse_arguments(["tests/test_service.py"])
    assert shell_parameter.value.code == 2
    assert injected_test.value.code == 2


def test_runtime_validation_failure_has_no_fallback(capsys: pytest.CaptureFixture[str]) -> None:
    runner = load_runner()
    with patch.object(
        runner,
        "validate_test_runtime",
        side_effect=runner.SecureTestError("configured test runtime is unavailable"),
    ):
        with pytest.raises(runner.SecureTestError):
            runner.fixed_test_command(False)
    assert sys.executable not in capsys.readouterr().out


def test_failure_output_redacts_secret_encoded_secret_and_dsn(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = load_runner()
    secret_file = tmp_path / "postgres-debug.env"
    password = "unsafe/password:value"
    write_secret(secret_file, password)
    dsn = runner.build_database_url(
        {"POSTGRES_USER": "test_user", "POSTGRES_PASSWORD": password, "POSTGRES_DB": "test_db"}
    )
    process_output = f"connection failed: {dsn} password={password} encoded={quote(password, safe='')}"

    runtime_python = Path("/project/devops-platform/shared/test-runtimes/test/bin/python")
    with (
        patch.object(runner, "validate_test_runtime", return_value=runtime_python),
        patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, "", process_output),
        ),
    ):
        assert runner.run([], secret_file) == 1

    output = capsys.readouterr().err
    assert password not in output
    assert quote(password, safe="") not in output
    assert dsn not in output
    assert "postgresql+psycopg://" not in output
    assert "[REDACTED]" in output


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are enforced on deployment hosts")
def test_secret_file_must_be_mode_600(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = load_runner()
    secret_file = tmp_path / "postgres-debug.env"
    write_secret(secret_file)
    secret_file.chmod(0o640)
    assert runner.run([], secret_file) == 78
    assert "permissions are unsafe" in capsys.readouterr().err
