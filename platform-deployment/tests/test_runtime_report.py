"""Tests for mandatory Python/image/wheelhouse runtime evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "runtime-report.py"


def load_module():
    """Load the hyphenated runtime report script for direct unit testing."""
    spec = importlib.util.spec_from_file_location("runtime_report", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_report_contains_required_evidence(tmp_path, monkeypatch, capsys) -> None:
    manifest = tmp_path / "cp312.json"
    manifest.write_text('{"implementation":"cp312"}\n', encoding="utf-8")
    output = tmp_path / "runtime.json"
    monkeypatch.setenv("PYTHON_IMAGE", "python:3.12.12-slim")
    monkeypatch.setenv("APP_IMAGE", "wkdevops/project-service:test-py312-debug")
    monkeypatch.setenv("WHEELHOUSE_ID", "cp312-test")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--manifest", str(manifest), "--output", str(output)])
    module = load_module()
    module.main()
    report = json.loads(capsys.readouterr().out)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert report == persisted
    assert report["python_version"]
    assert report["cache_tag"].startswith("cpython-")
    assert report["python_image"] == "python:3.12.12-slim"
    assert report["python_image_digest"]
    assert report["wheelhouse_manifest_sha256"]
    assert report["port_mapping"]["project_service"] > 0
