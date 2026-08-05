"""Wheel tag/hash fail-fast tests independent of network access."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "verify-wheelhouse.py"


def load_module():
    """Load the wheelhouse validator script as a test module."""
    spec = importlib.util.spec_from_file_location("verify_wheelhouse", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_wheel(directory: Path, filename: str) -> Path:
    """Create a minimal filename-level wheel fixture and matching checksum."""
    wheel = directory / filename
    wheel.write_bytes(b"wheel-fixture")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (directory / "SHA256SUMS").write_text(f"{digest}  {filename}\n", encoding="utf-8")
    return wheel


def test_cp312_accepts_hash_validated_pure_python_wheel(tmp_path) -> None:
    make_wheel(tmp_path, "example-1.0-py3-none-any.whl")
    entries = load_module().validate_wheelhouse(tmp_path, "cp312", tmp_path / "SHA256SUMS")
    assert entries[0]["pure_python"] is True


def test_cp312_accepts_older_cpython_abi3_wheel(tmp_path) -> None:
    make_wheel(tmp_path, "example-1.0-cp36-abi3-manylinux_2_17_x86_64.whl")
    entries = load_module().validate_wheelhouse(tmp_path, "cp312", tmp_path / "SHA256SUMS")
    assert entries[0]["pure_python"] is False


@pytest.mark.parametrize(
    "filename",
    (
        "example-1.0-cp313-cp313-manylinux_2_17_x86_64.whl",
        "example-1.0-cp312-cp312-win_amd64.whl",
        "example-1.0-cp312-cp312-macosx_11_0_x86_64.whl",
        "example-1.0-cp312-cp312-manylinux_2_17_aarch64.whl",
        "example-1.0-cp312-cp312-manylinux_2_17_i686.whl",
    ),
)
def test_cp312_rejects_wrong_abi_or_platform(tmp_path, filename: str) -> None:
    make_wheel(tmp_path, filename)
    with pytest.raises(ValueError):
        load_module().validate_wheelhouse(tmp_path, "cp312", tmp_path / "SHA256SUMS")


def test_hash_mismatch_is_rejected(tmp_path) -> None:
    make_wheel(tmp_path, "example-1.0-py3-none-any.whl")
    (tmp_path / "SHA256SUMS").write_text(
        f"{'0' * 64}  example-1.0-py3-none-any.whl\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_module().validate_wheelhouse(tmp_path, "cp312", tmp_path / "SHA256SUMS")


def test_real_cp312_wheelhouse_hash_manifest_and_service_runtime_closure() -> None:
    """Validate real wheel hashes and required seven-service runtime distributions."""
    wheelhouse = ROOT / "wheelhouse" / "linux-x86_64-cp312"
    manifest_path = ROOT / "wheelhouse" / "manifests" / "cp312.json"
    entries = load_module().validate_wheelhouse(
        wheelhouse,
        "cp312",
        wheelhouse / "SHA256SUMS",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validated = {entry["filename"]: entry["sha256"] for entry in entries}
    declared = {entry["filename"]: entry["sha256"] for entry in manifest["files"]}
    assert validated == declared

    available = {entry["name"].lower().replace("_", "-") for entry in entries}
    required = {
        "flask",
        "sqlalchemy",
        "alembic",
        "psycopg",
        "psycopg-binary",
        "gunicorn",
    }
    for service_name in (
        "iam-service",
        "workflow-service",
        "requirement-service",
        "tp-service",
        "td-service",
        "audit-service",
        "notification-service",
    ):
        project = tomllib.loads((ROOT / service_name / "pyproject.toml").read_text(encoding="utf-8"))
        direct = {
            dependency.split("[", 1)[0].split(">", 1)[0].split("<", 1)[0].lower()
            for dependency in project["project"]["dependencies"]
        }
        assert required <= direct | available
    assert required <= available
