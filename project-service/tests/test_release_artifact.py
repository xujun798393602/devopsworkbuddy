"""Automated inventory and permission tests for immutable release artifacts."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "build_release.py"


def load_builder() -> ModuleType:
    """Load the release builder as a module for isolated tests."""
    specification = importlib.util.spec_from_file_location("release_builder", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def write_fixture(source: Path) -> None:
    """Write representative deployable and non-deployable repository assets."""
    included = {
        "src/project_service/app.py": "APP = 'ok'\n",
        "migrations/versions/0001.py": "revision = '0001'\n",
        "scripts/run_postgres_integration.py": "#!/usr/bin/env python3\n",
        "scripts/build_release.py": "#!/usr/bin/env python3\n",
        "scripts/deploy.sh": "#!/usr/bin/env bash\n",
        "scripts/rollback.sh": "#!/usr/bin/env bash\n",
        "pyproject.toml": "[project]\nname='fixture'\n",
    }
    excluded = {
        "src/project_service/__pycache__/app.cpython-313.pyc": "cache",
        "migrations/versions/0001.pyc": "cache",
        ".pytest_cache/v/cache/nodeids": "tests",
        ".ruff_cache/0.12/cache": "ruff",
        ".venv/bin/python": "venv",
        ".venv-qa/lib/package.py": "venv",
        "venv/bin/python": "venv",
        "test-results/result.xml": "tests",
        "htmlcov/index.html": "coverage",
        "coverage.xml": "coverage",
        "build/output.whl": "build",
        "dist/package.whl": "dist",
        "node_modules/pkg/index.js": "node",
        "src/fixture.egg-info/PKG-INFO": "package-metadata",
        ".npm/_cacache/index": "node-cache",
        ".yarn/cache/pkg.zip": "node-cache",
        ".pnpm-store/v3/index": "node-cache",
        "npm-debug.log": "node-cache",
        "qa-output.log": "test-output",
    }
    for relative_path, content in {**included, **excluded}.items():
        path = source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits require a POSIX host")
def test_release_inventory_excludes_caches_and_enforces_permissions(tmp_path: Path) -> None:
    """A built artifact has exact hashes and no writable or cached objects."""
    builder = load_builder()
    source = tmp_path / "source"
    releases = tmp_path / "releases"
    source.mkdir()
    write_fixture(source)

    release, counts = builder.build_release(source, releases, "task66-test")
    verified = builder.verify_release(release)
    paths = {path.relative_to(release).as_posix() for path in release.rglob("*")}

    assert counts == verified
    assert verified["cache_files"] == 0
    assert verified["owner_writable"] == 0
    assert verified["group_or_other_writable"] == 0
    assert verified["executable_files"] == 4
    assert "src/project_service/app.py" in paths
    assert not any("__pycache__" in path or path.endswith(".pyc") for path in paths)
    assert not any(
        segment in path.split("/")
        for path in paths
        for segment in (".pytest_cache", ".ruff_cache", "node_modules", ".venv", "venv")
    )

    for path in release.rglob("*"):
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            assert mode == 0o555
        elif path.relative_to(release).as_posix() in builder.EXECUTABLE_PATHS:
            assert mode == 0o555
        else:
            assert mode == 0o444

    manifest = json.loads((release / builder.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["permission_policy"] == {
        "directories": "0555",
        "regular_files": "0444",
        "executable_entries": "0555",
        "owner_writable": 0,
        "group_or_other_writable": 0,
    }


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink and mode checks require a POSIX host")
def test_activation_preserves_task64_and_supports_rollback(tmp_path: Path) -> None:
    """Activation updates links atomically while preserving the audited old release."""
    builder = load_builder()
    source = tmp_path / "source"
    platform_root = tmp_path / "platform"
    releases = platform_root / "releases"
    task64 = releases / "task64"
    source.mkdir()
    task64.mkdir(parents=True)
    (task64 / "audit-marker").write_text("unchanged\n", encoding="utf-8")
    write_fixture(source)

    release, _ = builder.build_release(
        source,
        releases,
        "task66",
        platform_root=platform_root,
        previous_release=task64,
    )

    assert (platform_root / "current").resolve() == release.resolve()
    assert (platform_root / "previous").resolve() == task64.resolve()
    assert (task64 / "audit-marker").read_text(encoding="utf-8") == "unchanged\n"
    builder.replace_symlink(platform_root / "current", (platform_root / "previous").resolve())
    assert (platform_root / "current").resolve() == task64.resolve()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits require a POSIX host")
def test_verifier_rejects_cache_and_permission_regressions(tmp_path: Path) -> None:
    """Independent verification fails closed on extra cache or writable assets."""
    builder = load_builder()
    source = tmp_path / "source"
    releases = tmp_path / "releases"
    source.mkdir()
    write_fixture(source)
    release, _ = builder.build_release(source, releases, "task66")

    release.chmod(0o755)
    cached_directory = release / "migrations" / "versions" / "__pycache__"
    cached_directory.mkdir()
    cached_file = cached_directory / "0001.pyc"
    cached_file.write_bytes(b"cache")
    with pytest.raises(builder.ReleaseError, match="excluded cache|mode is not"):
        builder.verify_release(release)
