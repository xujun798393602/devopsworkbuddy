"""Hostile and valid XMind package tests."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from tp_service.design.safe_xmind import validate_xmind
from tp_service.domain import DomainError


def archive(entries: dict[str, bytes | str], compression: int = zipfile.ZIP_STORED) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression) as value:
        for name, content in entries.items():
            value.writestr(name, content)
    return output.getvalue()


def valid_content() -> str:
    return json.dumps([{"id": "sheet", "rootTopic": {"id": "root", "title": "Root", "children": {"attached": [{"id": "case", "title": "Case"}]}}}])


def test_normalized_ir_is_deterministic() -> None:
    first = validate_xmind(archive({"content.json": valid_content()}))
    second = validate_xmind(archive({"content.json": valid_content()}))
    assert first == second
    assert first["node_count"] == 2
    assert len(first["content_hash"]) == 64


@pytest.mark.parametrize(
    ("entries", "code"),
    [
        ({"../content.json": valid_content()}, "XMIND_ZIP_SLIP"),
        ({"content.json": valid_content(), "CONTENT.JSON": valid_content()}, "XMIND_ZIP_SLIP"),
        ({"content.json": json.dumps([{"id": "s", "rootTopic": {"id": "same", "title": "A", "children": {"attached": [{"id": "same", "title": "B"}]}}}])}, "XMIND_DUPLICATE_NODE"),
        ({"content.json": json.dumps([{"id": "s", "rootTopic": {"id": "root", "title": "https://evil.example"}}])}, "XMIND_ACTIVE_CONTENT"),
        ({"content.xml": "<!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><topic id='x'><title>&xxe;</title></topic>"}, "XMIND_ACTIVE_CONTENT"),
    ],
)
def test_hostile_archives_are_rejected(entries: dict[str, str], code: str) -> None:
    with pytest.raises(DomainError) as captured:
        validate_xmind(archive(entries))
    assert captured.value.code == code


def test_compression_bomb_ratio_is_rejected() -> None:
    data = archive({"content.json": b"A" * 100_000}, zipfile.ZIP_DEFLATED)
    with pytest.raises(DomainError) as captured:
        validate_xmind(data)
    assert captured.value.code == "XMIND_ZIP_BOMB"
