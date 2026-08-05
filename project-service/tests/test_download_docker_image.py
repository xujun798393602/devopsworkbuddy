import hashlib
import importlib.util
import json
import socket
import ssl
import sys
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "download_docker_image.py"
SPEC = importlib.util.spec_from_file_location("download_docker_image", SCRIPT)
assert SPEC and SPEC.loader
image_downloader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image_downloader)


def _archive_inputs() -> tuple[dict[str, object], bytes, bytes]:
    layer = b"layer-content"
    diff_id = "sha256:" + hashlib.sha256(layer).hexdigest()
    config = {
        "os": "linux",
        "architecture": "amd64",
        "rootfs": {"diff_ids": [diff_id]},
    }
    config_bytes = json.dumps(config).encode()
    manifest = {
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {"digest": "sha256:" + hashlib.sha256(config_bytes).hexdigest()},
        "layers": [
            {
                "digest": "sha256:" + hashlib.sha256(layer).hexdigest(),
                "mediaType": "application/vnd.oci.image.layer.v1.tar",
            }
        ],
    }
    return manifest, config_bytes, layer


def _build(output: Path, *, layer_failure: bool = False) -> dict[str, object]:
    manifest, config_bytes, layer = _archive_inputs()
    layer_result: bytes | OSError = OSError("network failed") if layer_failure else layer
    with (
        patch.object(image_downloader, "get_token", return_value="token"),
        patch.object(
            image_downloader,
            "get_manifest",
            return_value=(b"manifest", manifest, "sha256:" + "4" * 64),
        ),
        patch.object(
            image_downloader, "download_blob", side_effect=[config_bytes, layer_result]
        ),
    ):
        return image_downloader.build_archive(
            output, "library/python", "3.13-slim", "python:test"
        )


def test_default_opener_does_not_inherit_environment_proxy() -> None:
    with (
        patch.object(urllib.request, "getproxies") as getproxies,
        patch.object(urllib.request, "build_opener", return_value=Mock()) as build_opener,
    ):
        image_downloader.build_opener(proxy_env=False)
    getproxies.assert_not_called()
    assert build_opener.call_args.args[0].proxies == {}


def test_proxy_environment_is_read_only_when_explicitly_enabled() -> None:
    proxy = "http://user:super-secret@proxy.invalid:3128"
    with (
        patch.object(urllib.request, "getproxies", return_value={"https": proxy}) as getproxies,
        patch.object(urllib.request, "build_opener", return_value=Mock()) as build_opener,
    ):
        image_downloader.build_opener(proxy_env=True)
    getproxies.assert_called_once_with()
    assert build_opener.call_args.args[0].proxies == {"https": proxy}


def test_force_ipv4_preserves_tls_verification() -> None:
    context = Mock(verify_mode=ssl.CERT_REQUIRED, check_hostname=True)
    handler = urllib.request.HTTPSHandler(context=context)
    opener = Mock(handlers=[handler])
    with patch.object(urllib.request, "build_opener", return_value=opener) as build_opener:
        result = image_downloader.build_opener(proxy_env=False)
    assert result is opener
    assert isinstance(build_opener.call_args.args[0], urllib.request.ProxyHandler)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_force_ipv4_restores_after_normal_exception_nested_and_repeated() -> None:
    original = socket.getaddrinfo
    for _ in range(2):
        with image_downloader.force_ipv4_resolution(True):
            installed = socket.getaddrinfo
            assert installed is not original
            with image_downloader.force_ipv4_resolution(True):
                assert socket.getaddrinfo is not installed
            assert socket.getaddrinfo is installed
        assert socket.getaddrinfo is original
    with pytest.raises(RuntimeError, match="boom"):
        with image_downloader.force_ipv4_resolution(True):
            raise RuntimeError("boom")
    assert socket.getaddrinfo is original


def test_force_ipv4_wrapper_requests_only_af_inet() -> None:
    calls: list[int] = []

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        calls.append(family)
        return []

    original = socket.getaddrinfo
    socket.getaddrinfo = fake_getaddrinfo
    try:
        with image_downloader.force_ipv4_resolution(True):
            socket.getaddrinfo("example.invalid", 443, socket.AF_INET6)
        assert calls == [socket.AF_INET]
        assert socket.getaddrinfo is fake_getaddrinfo
    finally:
        socket.getaddrinfo = original


def test_layer_failure_leaves_no_new_output_or_temp(tmp_path: Path) -> None:
    output = tmp_path / "python-image.tar"
    with pytest.raises(OSError, match="network failed"):
        _build(output, layer_failure=True)
    assert not output.exists()
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_layer_failure_preserves_existing_output_bytes_hash_and_mtime(tmp_path: Path) -> None:
    output = tmp_path / "python-image.tar"
    output.write_bytes(b"verified-old-archive")
    before = (output.read_bytes(), hashlib.sha256(output.read_bytes()).hexdigest(), output.stat().st_mtime_ns)
    with pytest.raises(OSError, match="network failed"):
        _build(output, layer_failure=True)
    after = (output.read_bytes(), hashlib.sha256(output.read_bytes()).hexdigest(), output.stat().st_mtime_ns)
    assert after == before
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_replace_failure_preserves_existing_output_and_cleans_temp(tmp_path: Path) -> None:
    output = tmp_path / "python-image.tar"
    output.write_bytes(b"verified-old-archive")
    before = output.read_bytes()
    with patch.object(image_downloader.os, "replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            _build(output)
    assert output.read_bytes() == before
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_success_metadata_matches_final_archive(tmp_path: Path) -> None:
    output = tmp_path / "python-image.tar"
    metadata = _build(output)
    data = output.read_bytes()
    assert metadata["archive_sha256"] == hashlib.sha256(data).hexdigest()
    assert metadata["archive_size"] == len(data) == output.stat().st_size
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_main_redacts_proxy_url_token_and_authorization(capsys, tmp_path: Path) -> None:
    secret = "https://user:secret@proxy.example token-value Authorization: Bearer token-value"
    argv = ["download_docker_image.py", str(tmp_path / "image.tar"), "--proxy-env", "--force-ipv4"]
    with (
        patch.object(sys, "argv", argv),
        patch.object(image_downloader, "build_opener", return_value=Mock()),
        patch.object(image_downloader, "build_archive", side_effect=OSError(secret)),
        pytest.raises(SystemExit) as captured,
    ):
        image_downloader.main()
    assert captured.value.code == 1
    captured_output = capsys.readouterr()
    combined = captured_output.out + captured_output.err
    assert combined.strip() == "image_download_failed error_type=OSError error_code=DOWNLOAD_FAILED"
    for sensitive in ("user", "secret", "proxy.example", "token-value", "Authorization"):
        assert sensitive not in combined


def test_main_accepts_explicit_python_312_12_debug_reference(tmp_path: Path, capsys) -> None:
    argv = [
        "download_docker_image.py",
        str(tmp_path / "python-312.tar"),
        "--tag",
        "3.12.12-slim",
        "--repo-tag",
        "python:3.12.12-py312-wkdevops-offline",
        "--expected-python",
        "3.12.12",
    ]
    with (
        patch.object(sys, "argv", argv),
        patch.object(image_downloader, "build_opener", return_value=Mock()),
        patch.object(image_downloader, "build_archive", return_value={"os": "linux"}),
    ):
        image_downloader.main()
    assert json.loads(capsys.readouterr().out)["python_version_expected"] == "3.12.12"


def test_main_rejects_floating_or_mislabeled_python_312(tmp_path: Path) -> None:
    argv = [
        "download_docker_image.py",
        str(tmp_path / "python-312.tar"),
        "--tag",
        "3.12-slim",
        "--repo-tag",
        "python:debug",
        "--expected-python",
        "3.12.12",
    ]
    with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as captured:
        image_downloader.main()
    assert captured.value.code == 2


def test_network_failure_does_not_touch_unrelated_assets(tmp_path: Path) -> None:
    wheel = tmp_path / "wheelhouse" / "package.whl"
    checksum = tmp_path / "SHA256SUMS"
    wheel.parent.mkdir()
    wheel.write_bytes(b"wheel")
    checksum.write_text("original\n", encoding="utf-8")
    with patch.object(image_downloader, "get_token", side_effect=OSError("offline")):
        with pytest.raises(OSError, match="offline"):
            image_downloader.build_archive(
                tmp_path / "image.tar", "library/python", "3.13-slim", "python:test"
            )
    assert wheel.read_bytes() == b"wheel"
    assert checksum.read_text(encoding="utf-8") == "original\n"
