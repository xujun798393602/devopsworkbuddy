#!/usr/bin/env python3
"""Build, verify, and atomically activate an immutable deployment release."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

MANIFEST_NAME: Final = "RELEASE-MANIFEST.json"
EXECUTABLE_PATHS: Final = frozenset(
    {
        "scripts/build_release.py",
        "scripts/deploy.sh",
        "scripts/release_audit.py",
        "scripts/rollback.sh",
        "scripts/run_postgres_integration.py",
    }
)
EXCLUDED_DIRECTORY_NAMES: Final = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        ".workbuddy",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "test-output",
        "test-results",
        "venv",
    }
)
EXCLUDED_FILE_SUFFIXES: Final = (".pyc", ".pyo", ".coverage", ".log")
EXCLUDED_FILE_NAMES: Final = frozenset(
    {"coverage.xml", "junit.xml", "pytest-report.xml", "npm-debug.log", "yarn-error.log"}
)


class ReleaseError(RuntimeError):
    """Raised when a release cannot be built or verified safely."""


def is_deployment_asset(relative_path: Path) -> bool:
    """Return whether a repository path is allowed in a deployment release."""
    parts = relative_path.parts
    if any(part == "__pycache__" for part in parts):
        return False
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in parts[:-1]):
        return False
    if any(part.startswith(".venv") for part in parts[:-1]):
        return False
    if any(part.endswith(".egg-info") for part in parts):
        return False
    if any(
        fnmatch.fnmatch(part, pattern)
        for part in parts[:-1]
        for pattern in (".npm*", ".yarn*", ".pnpm-store*", ".node-gyp*")
    ):
        return False
    name = relative_path.name
    if name in EXCLUDED_FILE_NAMES or name.endswith(EXCLUDED_FILE_SUFFIXES):
        return False
    if name.endswith(".egg-info"):
        return False
    if name.endswith(".whl") and not parts[0] == "wheelhouse":
        return False
    return True


def iter_assets(source: Path) -> Iterator[Path]:
    """Yield deployable regular files in deterministic path order."""
    for path in sorted(source.rglob("*")):
        relative_path = path.relative_to(source)
        if path.is_symlink():
            raise ReleaseError(f"source symlink is not allowed: {relative_path.as_posix()}")
        if path.is_file() and is_deployment_asset(relative_path):
            yield relative_path


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_mode(relative_path: Path) -> int:
    """Return the immutable mode required for a release file."""
    return 0o555 if relative_path.as_posix() in EXECUTABLE_PATHS else 0o444


def write_manifest(release: Path, version: str) -> dict[str, object]:
    """Write and return the canonical release manifest."""
    files: list[dict[str, object]] = []
    for path in sorted(release.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        relative_path = path.relative_to(release)
        files.append(
            {
                "path": relative_path.as_posix(),
                "sha256": sha256_file(path),
                "mode": f"{expected_mode(relative_path):04o}",
                "size": path.stat().st_size,
            }
        )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "release_version": version,
        "permission_policy": {
            "directories": "0555",
            "regular_files": "0444",
            "executable_entries": "0555",
            "owner_writable": 0,
            "group_or_other_writable": 0,
        },
        "excluded_asset_classes": [
            "__pycache__/ and *.py[cod]",
            ".pytest_cache, .ruff_cache, .mypy_cache, and .tox",
            "local venv and .venv*",
            "test output, coverage output, logs, build, and dist",
            "node_modules and Node package-manager caches",
        ],
        "files": files,
    }
    (release / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def apply_permission_policy(release: Path) -> None:
    """Make every release object non-writable under the declared policy."""
    paths = sorted(release.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in paths:
        if path.is_file():
            relative_path = path.relative_to(release)
            path.chmod(expected_mode(relative_path))
        elif path.is_dir():
            path.chmod(0o555)
    release.chmod(0o555)


def verify_release(release: Path) -> dict[str, int]:
    """Verify manifest completeness, hashes, exclusions, and permission policy."""
    manifest_path = release / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseError("release manifest is missing or invalid") from error
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list):
        raise ReleaseError("release manifest file list is invalid")

    expected_entries: dict[str, dict[str, object]] = {}
    for entry in manifest_files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ReleaseError("release manifest contains an invalid entry")
        path_text = str(entry["path"])
        if path_text in expected_entries:
            raise ReleaseError(f"duplicate manifest path: {path_text}")
        expected_entries[path_text] = entry

    actual_files: dict[str, Path] = {}
    cache_files = 0
    owner_writable = 0
    group_or_other_writable = 0
    executable_files = 0
    directory_count = 1
    release_mode = stat.S_IMODE(release.stat().st_mode)
    if release_mode & stat.S_IWUSR:
        owner_writable += 1
    if release_mode & (stat.S_IWGRP | stat.S_IWOTH):
        group_or_other_writable += 1
    if release_mode != 0o555:
        raise ReleaseError("release directory mode is not 0555")
    for path in sorted(release.rglob("*")):
        relative_path = path.relative_to(release)
        if path.is_symlink():
            raise ReleaseError(f"release symlink is not allowed: {relative_path.as_posix()}")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & stat.S_IWUSR:
            owner_writable += 1
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            group_or_other_writable += 1
        if not is_deployment_asset(relative_path):
            cache_files += 1
        if path.is_dir():
            directory_count += 1
            if mode != 0o555:
                raise ReleaseError(f"directory mode is not 0555: {relative_path.as_posix()}")
        elif path.is_file():
            if path.name != MANIFEST_NAME:
                actual_files[relative_path.as_posix()] = path
            required_mode = expected_mode(relative_path)
            if mode != required_mode:
                raise ReleaseError(
                    f"file mode is not {required_mode:04o}: {relative_path.as_posix()}"
                )
            if required_mode == 0o555:
                executable_files += 1

    if cache_files:
        raise ReleaseError(f"release contains {cache_files} excluded cache/output assets")
    if owner_writable or group_or_other_writable:
        raise ReleaseError("release contains writable objects")
    if set(actual_files) != set(expected_entries):
        raise ReleaseError("manifest does not exactly match release file inventory")
    for relative_path, path in actual_files.items():
        entry = expected_entries[relative_path]
        if entry.get("sha256") != sha256_file(path):
            raise ReleaseError(f"hash mismatch: {relative_path}")
        if entry.get("size") != path.stat().st_size:
            raise ReleaseError(f"size mismatch: {relative_path}")
        if entry.get("mode") != f"{expected_mode(Path(relative_path)):04o}":
            raise ReleaseError(f"manifest mode mismatch: {relative_path}")

    return {
        "manifest_files": len(actual_files),
        "directories": directory_count,
        "cache_files": cache_files,
        "owner_writable": owner_writable,
        "group_or_other_writable": group_or_other_writable,
        "executable_files": executable_files,
    }


def replace_symlink(link: Path, target: Path) -> None:
    """Atomically replace a symlink without mutating its target."""
    temporary_link = link.parent / f".{link.name}.{os.getpid()}.tmp"
    temporary_link.unlink(missing_ok=True)
    temporary_link.symlink_to(target)
    os.replace(temporary_link, link)


def build_release(
    source: Path,
    releases: Path,
    version: str,
    *,
    platform_root: Path | None = None,
    previous_release: Path | None = None,
) -> tuple[Path, dict[str, int]]:
    """Build a new immutable release and optionally activate it atomically."""
    source = source.resolve()
    releases.mkdir(parents=True, exist_ok=True)
    destination = releases / version
    if destination.exists() or destination.is_symlink():
        raise ReleaseError(f"release already exists: {destination}")
    staging = Path(tempfile.mkdtemp(prefix=f".{version}.", dir=releases))
    try:
        for relative_path in iter_assets(source):
            output_path = staging / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative_path, output_path)
        write_manifest(staging, version)
        apply_permission_policy(staging)
        counts = verify_release(staging)
        os.replace(staging, destination)
        counts = verify_release(destination)
        if platform_root is not None:
            if previous_release is None or not previous_release.is_dir():
                raise ReleaseError("an existing previous release is required for activation")
            replace_symlink(platform_root / "previous", previous_release.resolve())
            replace_symlink(platform_root / "current", destination.resolve())
        return destination, counts
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def parse_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    """Parse release-builder command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("releases", type=Path, nargs="?")
    parser.add_argument("version", nargs="?")
    parser.add_argument("--platform-root", type=Path)
    parser.add_argument("--previous-release", type=Path)
    parser.add_argument("--verify", type=Path)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Build or independently verify an immutable release."""
    options = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    try:
        if options.verify is not None:
            counts = verify_release(options.verify)
            release = options.verify
        else:
            if options.source is None or options.releases is None or options.version is None:
                raise ReleaseError("source, releases, and version are required when building")
            release, counts = build_release(
                options.source,
                options.releases,
                options.version,
                platform_root=options.platform_root,
                previous_release=options.previous_release,
            )
    except ReleaseError as error:
        print(f"release-build: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"release": str(release), **counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
