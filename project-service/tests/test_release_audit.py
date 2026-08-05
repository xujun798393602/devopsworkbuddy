"""Tests for the deterministic release audit algorithm."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "release_audit.py"


def load_auditor() -> ModuleType:
    """Load the audit tool as a module."""
    specification = importlib.util.spec_from_file_location("release_auditor", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


@pytest.mark.skipif(os.name != "posix", reason="Audit ownership and modes require POSIX")
def test_audit_is_reproducible_and_detects_changes(tmp_path: Path) -> None:
    auditor = load_auditor()
    release = tmp_path / "task64"
    nested = release / "nested"
    nested.mkdir(parents=True)
    payload = nested / "payload.txt"
    payload.write_text("stable\n", encoding="utf-8")
    release.chmod(0o555)
    nested.chmod(0o555)
    payload.chmod(0o444)

    first = auditor.create_audit(release)
    second = auditor.create_audit(release)
    assert first == second
    assert first["algorithm_version"] == "wkdevops-release-audit-v1"
    assert first["excluded_metadata"] == ["mtime_ns", "inode"]

    audit_path = tmp_path / "release-audit.json"
    audit_path.write_text(json.dumps(first, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert auditor.verify_audit(audit_path) == first

    payload.chmod(0o644)
    payload.write_text("changed\n", encoding="utf-8")
    with pytest.raises(auditor.AuditError, match="recomputation mismatch"):
        auditor.verify_audit(audit_path)
