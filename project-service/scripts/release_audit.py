#!/usr/bin/env python3
"""Create or verify a deterministic, independently reproducible release audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

ALGORITHM_VERSION: Final = "wkdevops-release-audit-v1"
SCHEMA_VERSION: Final = 1
RECORD_SEPARATOR: Final = b"\x1e"
FIELD_SEPARATOR: Final = b"\x1f"


class AuditError(RuntimeError):
    """Raised when a release inventory cannot be audited safely."""


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash file content exactly as stored, without text normalization."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_inventory(root: Path) -> Iterator[tuple[Path, os.stat_result]]:
    """Yield lstat inventory in UTF-8 bytewise relative-path order."""
    paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().encode("utf-8"))
    for path in paths:
        relative_path = path.relative_to(root)
        try:
            relative_path.as_posix().encode("utf-8", errors="strict")
            metadata = path.lstat()
        except (OSError, UnicodeError) as error:
            raise AuditError("release contains an unreadable or non-UTF-8 path") from error
        if not any(
            predicate(metadata.st_mode)
            for predicate in (stat.S_ISDIR, stat.S_ISREG, stat.S_ISLNK)
        ):
            raise AuditError(f"unsupported file type: {relative_path.as_posix()}")
        yield relative_path, metadata


def metadata_record(entry: dict[str, object]) -> bytes:
    """Encode one metadata record using documented field and record separators."""
    fields = (
        str(entry["path"]),
        str(entry["type"]),
        str(entry["mode"]),
        str(entry["uid"]),
        str(entry["gid"]),
        str(entry["size"]),
    )
    return FIELD_SEPARATOR.join(field.encode("utf-8") for field in fields) + RECORD_SEPARATOR


def content_record(entry: dict[str, object]) -> bytes:
    """Encode one regular-file content record deterministically."""
    return FIELD_SEPARATOR.join(
        (str(entry["path"]).encode("utf-8"), str(entry["sha256"]).encode("ascii"))
    ) + RECORD_SEPARATOR


def create_audit(root: Path) -> dict[str, object]:
    """Create the canonical audit object for an existing release root."""
    root = root.resolve(strict=True)
    entries: list[dict[str, object]] = []
    metadata_digest = hashlib.sha256()
    content_digest = hashlib.sha256()
    for relative_path, metadata in iter_inventory(root):
        is_file = stat.S_ISREG(metadata.st_mode)
        is_symlink = stat.S_ISLNK(metadata.st_mode)
        link_target = os.readlink(root / relative_path) if is_symlink else None
        entry: dict[str, object] = {
            "path": relative_path.as_posix(),
            "type": "file" if is_file else "symlink" if is_symlink else "directory",
            "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
            "uid": metadata.st_uid,
            "gid": metadata.st_gid,
            "size": metadata.st_size if is_file or is_symlink else 0,
            "sha256": (
                sha256_file(root / relative_path)
                if is_file
                else sha256_bytes(link_target.encode("utf-8"))
                if link_target is not None
                else None
            ),
        }
        entries.append(entry)
        metadata_digest.update(metadata_record(entry))
        if is_file or is_symlink:
            content_digest.update(content_record(entry))
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "root": str(root),
        "path_rules": {
            "base": "root-relative",
            "encoding": "UTF-8 strict",
            "separator": "/",
            "sort": "ascending unsigned UTF-8 bytes",
            "symlinks": "inventory link itself; hash raw UTF-8 link target",
        },
        "inventory_fields": ["path", "type", "mode", "uid", "gid", "size", "sha256"],
        "excluded_metadata": ["mtime_ns", "inode"],
        "hash_rules": {
            "algorithm": "SHA-256",
            "field_separator_hex": "1f",
            "record_separator_hex": "1e",
            "metadata_fields": ["path", "type", "mode", "uid", "gid", "size"],
            "content_fields": ["path", "sha256"],
            "file_content": "raw bytes; symlink content is raw UTF-8 link target",
            "directory_size": 0,
            "null_sha256": "JSON null; omitted from content root input",
        },
        "entries": entries,
        "metadata_root_sha256": metadata_digest.hexdigest(),
        "content_root_sha256": content_digest.hexdigest(),
    }


def verify_audit(audit_path: Path, root_override: Path | None = None) -> dict[str, object]:
    """Independently recompute an audit and require exact canonical equality."""
    try:
        expected = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuditError("audit document is unreadable or invalid") from error
    if expected.get("algorithm_version") != ALGORITHM_VERSION:
        raise AuditError("unsupported audit algorithm version")
    root_value = root_override if root_override is not None else Path(str(expected.get("root", "")))
    actual = create_audit(root_value)
    if root_override is not None:
        expected = dict(expected)
        expected["root"] = str(root_value.resolve(strict=True))
    if actual != expected:
        raise AuditError("audit recomputation mismatch")
    return actual


def parse_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    """Parse audit creation and verification arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--create", type=Path, metavar="ROOT")
    operation.add_argument("--verify", type=Path, metavar="AUDIT_JSON")
    parser.add_argument("--root", type=Path, help="Override root only when independently verifying.")
    parser.add_argument("--output", type=Path, help="Write canonical JSON instead of standard output.")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Create or verify an audit, printing no file content or environment data."""
    options = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    try:
        if options.create is not None:
            audit = create_audit(options.create)
        else:
            audit = verify_audit(options.verify, options.root)
        output = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if options.output is not None:
            options.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
        return 0
    except AuditError as error:
        sys.stderr.write(f"release-audit: {error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
