#!/usr/bin/env python3
"""Emit auditable Python and offline-asset runtime metadata as JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def file_sha256(path: Path | None) -> str:
    """Return a manifest digest, or an empty string when no manifest was supplied."""
    if path is None:
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_digest(reference: str) -> str:
    """Read an image repository digest without modifying Docker state."""
    if not reference:
        return ""
    try:
        output = subprocess.check_output(
            ["docker", "image", "inspect", reference, "--format", "{{json .RepoDigests}}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return output


def main() -> None:
    """Write deterministic runtime evidence to stdout and optionally a file."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    image = os.environ.get("PYTHON_IMAGE", "python:3.13-slim")
    report = {
        "python_version": platform.python_version(),
        "python_version_full": sys.version,
        "cache_tag": sys.implementation.cache_tag,
        "implementation": platform.python_implementation(),
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
        "platform": platform.platform(),
        "python_image": image,
        "python_image_digest": image_digest(image),
        "app_image": os.environ.get("APP_IMAGE", "wkdevops/project-service:dev-py313"),
        "wheelhouse_id": os.environ.get("WHEELHOUSE_ID", ""),
        "wheelhouse_manifest_sha256": file_sha256(args.manifest),
        "compose_project_name": os.environ.get(
            "COMPOSE_PROJECT_NAME", "wkdevops-project-service"
        ),
        "port_mapping": {
            "project_service": int(os.environ.get("PROJECT_SERVICE_PORT", "18080")),
        },
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
