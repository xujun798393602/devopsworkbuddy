#!/usr/bin/env python3
"""Fail-fast validation for an offline Linux x86_64 CPython wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Final

from packaging.tags import Tag
from packaging.utils import canonicalize_name, parse_wheel_filename

LINUX_X86_64_PLATFORMS: Final[tuple[str, ...]] = (
    "manylinux",
    "musllinux",
    "linux_x86_64",
)
FORBIDDEN_PLATFORM_PARTS: Final[tuple[str, ...]] = (
    "win",
    "macosx",
    "arm",
    "aarch64",
    "i686",
    "i386",
    "ppc",
    "s390x",
)


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_hashes(path: Path) -> dict[str, str]:
    """Load GNU sha256sum formatted entries and reject malformed lines."""
    hashes: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line)
        if match is None:
            raise ValueError(f"Malformed SHA256SUMS line {line_number}: {raw_line!r}")
        digest, filename = match.groups()
        if filename in hashes:
            raise ValueError(f"Duplicate SHA256SUMS filename: {filename}")
        hashes[filename] = digest.lower()
    return hashes


def validate_tag(tag: Tag, implementation: str) -> None:
    """Reject tags incompatible with Linux x86_64 and the requested CPython ABI."""
    text = str(tag).lower()
    if any(part in text for part in FORBIDDEN_PLATFORM_PARTS):
        raise ValueError(f"Forbidden platform tag: {tag}")
    if tag.interpreter.startswith("cp") and tag.interpreter != implementation:
        target_version = int(implementation.removeprefix("cp"))
        wheel_version = int(tag.interpreter.removeprefix("cp"))
        if tag.abi != "abi3" or wheel_version > target_version:
            raise ValueError(f"Wrong interpreter tag {tag.interpreter}; expected {implementation}")
    if tag.abi.startswith("cp") and tag.abi != implementation:
        raise ValueError(f"Wrong ABI tag {tag.abi}; expected {implementation}")
    if tag.platform != "any" and not any(
        tag.platform.startswith(platform) for platform in LINUX_X86_64_PLATFORMS
    ):
        raise ValueError(f"Non-Linux-x86_64 platform tag: {tag.platform}")


def validate_wheelhouse(
    wheelhouse: Path,
    implementation: str,
    hashes_path: Path,
) -> list[dict[str, object]]:
    """Validate every wheel tag/hash and return deterministic manifest entries."""
    wheels = sorted(wheelhouse.glob("*.whl"), key=lambda item: item.name.lower())
    if not wheels:
        raise ValueError(f"No wheels found in {wheelhouse}")
    expected_hashes = load_hashes(hashes_path)
    wheel_names = {wheel.name for wheel in wheels}
    if set(expected_hashes) != wheel_names:
        missing = sorted(wheel_names - set(expected_hashes))
        extra = sorted(set(expected_hashes) - wheel_names)
        raise ValueError(f"SHA256SUMS closure mismatch missing={missing} extra={extra}")

    entries: list[dict[str, object]] = []
    for wheel in wheels:
        distribution, version, _build, tags = parse_wheel_filename(wheel.name)
        if not tags:
            raise ValueError(f"Wheel has no tags: {wheel.name}")
        for tag in tags:
            validate_tag(tag, implementation)
        digest = sha256_file(wheel)
        if digest != expected_hashes[wheel.name]:
            raise ValueError(f"SHA-256 mismatch: {wheel.name}")
        entries.append(
            {
                "filename": wheel.name,
                "name": canonicalize_name(distribution),
                "version": str(version),
                "sha256": digest,
                "size": wheel.stat().st_size,
                "tags": sorted(str(tag) for tag in tags),
                "pure_python": all(tag.abi == "none" and tag.platform == "any" for tag in tags),
            }
        )
    return entries


def main() -> None:
    """Run command-line validation and optionally write a manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("--implementation", choices=("cp312", "cp313"), required=True)
    parser.add_argument("--sha256sums", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--python-version", default="")
    args = parser.parse_args()
    hashes_path = args.sha256sums or args.wheelhouse / "SHA256SUMS"
    entries = validate_wheelhouse(args.wheelhouse, args.implementation, hashes_path)
    document = {
        "schema_version": 1,
        "python_version": args.python_version,
        "implementation": args.implementation,
        "cache_tag": f"cpython-{args.implementation.removeprefix('cp')}",
        "os": "linux",
        "architecture": "x86_64",
        "package_count": len(entries),
        "files": entries,
    }
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.manifest is not None:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"wheelhouse_validation_failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
