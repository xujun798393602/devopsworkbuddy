"""Select non-conflicting host ports and create an auditable deployment environment."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent


def select_port(start: int = 18080, reserved: set[int] | None = None) -> int:
    """Return the first bindable TCP port without stopping any existing process."""
    used = reserved if reserved is not None else set()
    for port in range(start, 65536):
        if port in used:
            continue
        with socket.socket() as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                continue
            used.add(port)
            return port
    raise RuntimeError("No free TCP port available")


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a deployment asset."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """Write deploy.env and deployment.json without modifying running containers."""
    reserved: set[int] = set()
    project_port = select_port(int(os.environ.get("PROJECT_SERVICE_PORT_START", "18080")), reserved)
    version = os.environ.get("DEPLOY_VERSION", datetime.now(UTC).strftime("%Y%m%d%H%M%S"))
    implementation = os.environ.get("PYTHON_IMPLEMENTATION", "cp313")
    debug = implementation == "cp312"
    suffix = "py312-debug" if debug else "dev"
    python_image = os.environ.get(
        "PYTHON_IMAGE", "python:3.12.12-slim" if debug else "python:3.13-slim"
    )
    expected_version = os.environ.get("PYTHON_VERSION_EXPECTED", "3.12.12" if debug else "3.13")
    app_image = os.environ.get(
        "APP_IMAGE",
        "wkdevops/project-service:dev-py312-debug"
        if debug
        else "wkdevops/project-service:dev-py313",
    )
    wheelhouse_id = os.environ.get(
        "WHEELHOUSE_ID", "cp312-linux-x86_64-debug" if debug else "cp313-production"
    )
    manifest = REPOSITORY_ROOT / "wheelhouse" / "manifests" / f"{implementation}.json"
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unversioned-source"
    environment = {
        "COMPOSE_PROJECT_NAME": f"wkdevops-project-service-{suffix}" if debug else "wkdevops-project-service",
        "PROJECT_SERVICE_PORT": str(project_port),
        "PYTHON_IMAGE": python_image,
        "PYTHON_IMPLEMENTATION": implementation,
        "PYTHON_VERSION_EXPECTED": expected_version,
        "APP_IMAGE": app_image,
        "WHEELHOUSE_DIR": f"wheelhouse/linux-x86_64-{implementation}",
        "WHEELHOUSE_ID": wheelhouse_id,
        "LOCK_FILE": f"constraints/{implementation}-linux-x86_64.txt",
        "API_CONTAINER_NAME": f"wkDEVOPS-project-service-api-{suffix}",
        "MIGRATE_CONTAINER_NAME": f"wkDEVOPS-project-service-migrate-{suffix}",
        "DB_CONTAINER_NAME": f"wkDEVOPS-project-service-postgres-{suffix}",
        "DB_VOLUME_NAME": f"wkDEVOPS-project-service-data-{suffix}",
    }
    payload = {
        "version": version,
        "commit": commit,
        "source": "project-service",
        "python_image": python_image,
        "python_version_expected": expected_version,
        "app_image": app_image,
        "wheelhouse_id": wheelhouse_id,
        "wheelhouse_manifest_sha256": sha256_file(manifest) if manifest.is_file() else "unavailable",
        "platform": "linux/x86_64",
        "port_mapping": {"project_service": project_port},
        "selected_at": datetime.now(UTC).isoformat(),
    }
    lines = [f"{key}={value}" for key, value in environment.items()]
    _atomic_write(ROOT / "deploy.env", "\n".join(lines) + "\n")
    _atomic_write(ROOT / "deployment.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _atomic_write(path: Path, content: str) -> None:
    """Atomically replace a UTF-8 metadata file."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
