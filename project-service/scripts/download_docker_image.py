"""Download an official Docker Hub image as an auditable docker-load archive."""

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
import socket
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AUTH_URL = "https://auth.docker.io/token"
REGISTRY = "https://registry-1.docker.io"
ACCEPT_INDEX = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
ACCEPT_MANIFEST = ", ".join(
    (
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    )
)
_OPENER: urllib.request.OpenerDirector | None = None

INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}


def sha256_digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def require_sha256(digest: str, data: bytes) -> None:
    if not digest.startswith("sha256:"):
        raise ValueError(f"Unsupported digest algorithm: {digest}")
    if sha256_digest(data) != digest:
        raise ValueError(f"Digest verification failed for {digest}")


def build_opener(proxy_env: bool, force_ipv4: bool = False) -> urllib.request.OpenerDirector:
    """Create an opener using only explicitly requested environment proxy settings."""
    proxies = urllib.request.getproxies() if proxy_env else {}
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))


@contextlib.contextmanager
def force_ipv4_resolution(enabled: bool):
    """Temporarily constrain DNS resolution to IPv4 for one download lifecycle."""
    if not enabled:
        yield
        return
    original_getaddrinfo = socket.getaddrinfo

    def ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = ipv4_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def request_bytes(
    url: str,
    token: str = "",
    accept: str = "",
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[bytes, Any]:
    headers = {"User-Agent": "wkdevops-offline-image-fetcher/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    active_opener = (
        opener or _OPENER or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )
    with active_opener.open(request, timeout=120) as response:
        return response.read(), response.headers


def get_token(repository: str) -> str:
    query = urllib.parse.urlencode(
        {"service": "registry.docker.io", "scope": f"repository:{repository}:pull"}
    )
    body, _ = request_bytes(f"{AUTH_URL}?{query}")
    token = json.loads(body)["token"]
    if not isinstance(token, str) or not token:
        raise ValueError("Registry returned an invalid anonymous token")
    return token


def get_manifest(
    repository: str, reference: str, token: str, accept: str
) -> tuple[bytes, dict[str, Any], str]:
    encoded = urllib.parse.quote(reference, safe=":")
    body, headers = request_bytes(f"{REGISTRY}/v2/{repository}/manifests/{encoded}", token, accept)
    digest = headers.get("Docker-Content-Digest", "")
    if not digest:
        raise ValueError("Registry manifest response omitted Docker-Content-Digest")
    require_sha256(digest, body)
    document = json.loads(body)
    if not isinstance(document, dict):
        raise ValueError("Registry returned a non-object manifest")
    return body, document, digest


def select_linux_amd64(index: dict[str, Any]) -> str:
    matches = []
    for descriptor in index.get("manifests", []):
        platform = descriptor.get("platform", {})
        if (
            platform.get("os") == "linux"
            and platform.get("architecture") == "amd64"
            and platform.get("variant") in (None, "")
        ):
            matches.append(descriptor["digest"])
    if len(matches) != 1:
        raise ValueError(f"Expected one linux/amd64 manifest, found {len(matches)}")
    return matches[0]


def download_blob(repository: str, digest: str, token: str) -> bytes:
    body, _ = request_bytes(f"{REGISTRY}/v2/{repository}/blobs/{digest}", token)
    require_sha256(digest, body)
    return body


def uncompress_layer(blob: bytes, media_type: str) -> bytes:
    if media_type.endswith(".gzip") or blob.startswith(b"\x1f\x8b"):
        return gzip.decompress(blob)
    if media_type in {
        "application/vnd.docker.image.rootfs.diff.tar",
        "application/vnd.oci.image.layer.v1.tar",
    }:
        return blob
    raise ValueError(f"Unsupported layer compression/media type: {media_type}")


def add_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(data))


def build_archive(output: Path, repository: str, tag: str, repo_tag: str) -> dict[str, Any]:
    token = get_token(repository)
    _, document, top_digest = get_manifest(repository, tag, token, ACCEPT_INDEX)
    media_type = document.get("mediaType", "")
    selected_digest = top_digest
    if media_type in INDEX_TYPES or "manifests" in document:
        selected_digest = select_linux_amd64(document)
        _, document, returned_digest = get_manifest(
            repository, selected_digest, token, ACCEPT_MANIFEST
        )
        if returned_digest != selected_digest:
            raise ValueError("Selected manifest digest changed during retrieval")
    config_descriptor = document["config"]
    config_digest = config_descriptor["digest"]
    config_bytes = download_blob(repository, config_digest, token)
    config = json.loads(config_bytes)
    if config.get("os") != "linux" or config.get("architecture") != "amd64":
        raise ValueError("Image config is not linux/amd64")
    layers = document.get("layers", [])
    diff_ids = config.get("rootfs", {}).get("diff_ids", [])
    if len(layers) != len(diff_ids) or not layers:
        raise ValueError("Manifest layers do not match config rootfs.diff_ids")
    output.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(file_descriptor)
    temporary_output = Path(temporary_name)
    try:
        with tarfile.open(temporary_output, "w") as archive:
            layer_names = []
            for index, (descriptor, diff_id) in enumerate(zip(layers, diff_ids, strict=True)):
                blob = download_blob(repository, descriptor["digest"], token)
                layer = uncompress_layer(blob, descriptor.get("mediaType", ""))
                require_sha256(diff_id, layer)
                directory = hashlib.sha256(f"{index}:{diff_id}".encode()).hexdigest()
                layer_name = f"{directory}/layer.tar"
                add_bytes(archive, layer_name, layer)
                add_bytes(archive, f"{directory}/VERSION", b"1.0")
                add_bytes(archive, f"{directory}/json", b"{}")
                layer_names.append(layer_name)
            config_name = f"{config_digest.removeprefix('sha256:')}.json"
            manifest = [{"Config": config_name, "RepoTags": [repo_tag], "Layers": layer_names}]
            repository_name, repository_tag = repo_tag.rsplit(":", 1)
            repositories = {
                repository_name: {repository_tag: config_digest.removeprefix("sha256:")}
            }
            add_bytes(archive, config_name, config_bytes)
            add_bytes(archive, "manifest.json", json.dumps(manifest).encode())
            add_bytes(archive, "repositories", json.dumps(repositories).encode())
        archive_sha256 = hashlib.sha256(temporary_output.read_bytes()).hexdigest()
        archive_size = temporary_output.stat().st_size
        if archive_size <= 0:
            raise ValueError("Generated archive is empty")
        os.replace(temporary_output, output)
    finally:
        temporary_output.unlink(missing_ok=True)
    return {
        "source_repository": repository,
        "source_tag": tag,
        "index_digest": top_digest,
        "selected_manifest_digest": selected_digest,
        "config_digest": config_digest,
        "os": "linux",
        "architecture": "amd64",
        "layer_count": len(layers),
        "repo_tag": repo_tag,
        "archive_filename": output.name,
        "archive_sha256": archive_sha256,
        "archive_size": archive_size,
    }


def main() -> None:
    global _OPENER
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--repository", default="library/python")
    parser.add_argument("--tag", default="3.13-slim")
    parser.add_argument("--repo-tag", default="python:3.13-slim-wkdevops-offline")
    parser.add_argument("--expected-python", choices=("3.12.12", "3.13"), default="3.13")
    parser.add_argument(
        "--proxy-env", action="store_true", help="Use HTTP(S)_PROXY from the environment"
    )
    parser.add_argument("--force-ipv4", action="store_true")
    args = parser.parse_args()
    if args.expected_python == "3.12.12":
        if args.tag != "3.12.12-slim" or "py312" not in args.repo_tag:
            parser.error("Python 3.12.12 assets require --tag 3.12.12-slim and a py312 repo tag")
    elif "py312" in args.repo_tag or args.tag.startswith("3.12"):
        parser.error("Python 3.13 baseline assets must not use a py312/3.12 tag")
    _OPENER = build_opener(args.proxy_env)
    try:
        with force_ipv4_resolution(args.force_ipv4):
            result = build_archive(args.output, args.repository, args.tag, args.repo_tag)
            result["python_version_expected"] = args.expected_python
    except Exception as error:
        print(
            f"image_download_failed error_type={type(error).__name__} error_code=DOWNLOAD_FAILED",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
