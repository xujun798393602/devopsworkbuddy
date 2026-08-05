"""In-memory defensive XMind ZIP validator and normalized parser."""
from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree

from tp_service.domain import DomainError

MAX_UPLOAD = 50 * 1024 * 1024
MAX_EXPANDED = 200 * 1024 * 1024
MAX_ENTRIES = 2_000
MAX_NODES = 10_000
MAX_CASES = 1_000
MAX_DEPTH = 20
MAX_TITLE = 500
MAX_NOTES = 20_000
ALLOWED = {"content.json", "content.xml", "metadata.json", "manifest.json"}
DANGEROUS = re.compile(
    r"(?i)(javascript:|https?://|file:|<!doctype|<!entity|<script|macro|vbscript|cmd\(|powershell|formula)"
)


def _validate_name(name: str, seen: set[str]) -> str:
    if "\x00" in name or "\\" in name or name.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", name):
        raise DomainError("XMIND_ZIP_SLIP", "Unsafe ZIP entry path", 422)
    path = PurePosixPath(name)
    normalized = path.as_posix().casefold()
    if ".." in path.parts or normalized in seen:
        raise DomainError("XMIND_ZIP_SLIP", "Duplicate or traversing ZIP entry", 422)
    seen.add(normalized)
    return path.as_posix()


def _json_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise DomainError("XMIND_DEPTH_EXCEEDED", "JSON nesting exceeds 20", 422)
    if isinstance(value, dict):
        for item in value.values():
            _json_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _json_depth(item, depth + 1)


def _topic_children(topic: dict[str, Any]) -> list[dict[str, Any]]:
    children = topic.get("children", {})
    if not isinstance(children, dict):
        return []
    values: list[dict[str, Any]] = []
    for group in ("attached", "detached"):
        items = children.get(group, [])
        if isinstance(items, list):
            values.extend(item for item in items if isinstance(item, dict))
    return values


def _normalize_json(parsed: Any) -> dict[str, Any]:
    sheets = parsed if isinstance(parsed, list) else [parsed]
    normalized_nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    case_count = 0

    def visit(topic: dict[str, Any], parent_id: str | None, depth: int) -> None:
        nonlocal case_count
        if depth > MAX_DEPTH:
            raise DomainError("XMIND_DEPTH_EXCEEDED", "Topic depth exceeds 20", 422)
        node_id = str(topic.get("id", "")).strip()
        title = str(topic.get("title", "")).strip()
        notes_value = topic.get("notes", "")
        notes = str(notes_value.get("plain", {}).get("content", "")) if isinstance(notes_value, dict) else str(notes_value)
        if not node_id or node_id in seen_ids:
            raise DomainError("XMIND_DUPLICATE_NODE", "Topic ids must be present and unique", 422)
        if not title or len(title) > MAX_TITLE or len(notes) > MAX_NOTES:
            raise DomainError("XMIND_INVALID_TOPIC", "Topic title or notes length is invalid", 422)
        seen_ids.add(node_id)
        children = _topic_children(topic)
        if not children:
            case_count += 1
        normalized_nodes.append({"id": node_id, "parent_id": parent_id, "title": title, "notes": notes, "depth": depth})
        if len(normalized_nodes) > MAX_NODES or case_count > MAX_CASES:
            raise DomainError("XMIND_NODE_LIMIT", "XMind node or case limit was exceeded", 422)
        for child in children:
            visit(child, node_id, depth + 1)

    for sheet in sheets:
        if not isinstance(sheet, dict) or not isinstance(sheet.get("rootTopic"), dict):
            raise DomainError("XMIND_TEMPLATE_REQUIRED", "Expected XMind rootTopic schema", 422)
        visit(sheet["rootTopic"], None, 0)
    canonical = json.dumps(normalized_nodes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {
        "format": "json",
        "node_count": len(normalized_nodes),
        "case_count": case_count,
        "nodes": normalized_nodes,
        "content_hash": hashlib.sha256(canonical).hexdigest(),
    }


def _normalize_xml(content: bytes) -> dict[str, Any]:
    root = ElementTree.fromstring(content)
    elements = list(root.iter())
    if len(elements) > MAX_NODES:
        raise DomainError("XMIND_NODE_LIMIT", "XMind exceeds 10000 nodes", 422)
    topics = [element for element in elements if element.tag.rsplit("}", 1)[-1] == "topic"]
    seen_ids: set[str] = set()
    nodes: list[dict[str, Any]] = []
    for topic in topics:
        node_id = str(topic.attrib.get("id", "")).strip()
        if not node_id or node_id in seen_ids:
            raise DomainError("XMIND_DUPLICATE_NODE", "Topic ids must be present and unique", 422)
        seen_ids.add(node_id)
        title = ""
        notes = ""
        for child in topic:
            local = child.tag.rsplit("}", 1)[-1]
            if local == "title":
                title = "".join(child.itertext()).strip()
            elif local == "notes":
                notes = "".join(child.itertext()).strip()
        if not title or len(title) > MAX_TITLE or len(notes) > MAX_NOTES:
            raise DomainError("XMIND_INVALID_TOPIC", "Topic title or notes length is invalid", 422)
        nodes.append({"id": node_id, "title": title, "notes": notes})
    if not nodes:
        raise DomainError("XMIND_TEMPLATE_REQUIRED", "Expected XMind topic schema", 422)
    canonical = json.dumps(nodes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {
        "format": "xml",
        "node_count": len(nodes),
        "case_count": min(len(nodes), MAX_CASES),
        "nodes": nodes,
        "content_hash": hashlib.sha256(canonical).hexdigest(),
    }


def validate_xmind(data: bytes) -> dict[str, Any]:
    """Validate all archive limits and return deterministic normalized IR."""
    if len(data) > MAX_UPLOAD or not data.startswith(b"PK"):
        raise DomainError("INVALID_XMIND", "XMind must be a ZIP no larger than 50 MiB", 413)
    seen: set[str] = set()
    expanded = 0
    actual_total = 0
    content: bytes | None = None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES:
                raise DomainError("XMIND_TOO_MANY_ENTRIES", "XMind exceeds 2000 entries", 422)
            for info in entries:
                name = _validate_name(info.filename, seen)
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if info.flag_bits & 1 or stat.S_ISLNK(mode) or (file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR}):
                    raise DomainError("XMIND_UNSAFE_ENTRY", "Encrypted, linked, or special entries are forbidden", 422)
                expanded += info.file_size
                if info.file_size > MAX_UPLOAD or expanded > MAX_EXPANDED or info.file_size / max(info.compress_size, 1) > 100:
                    raise DomainError("XMIND_ZIP_BOMB", "XMind expansion limits were exceeded", 422)
                allowed = name in ALLOWED or name.startswith("Thumbnails/")
                if not allowed or info.is_dir():
                    continue
                with archive.open(info) as stream:
                    chunks: list[bytes] = []
                    actual = 0
                    while chunk := stream.read(64 * 1024):
                        actual += len(chunk)
                        actual_total += len(chunk)
                        if actual > MAX_UPLOAD or actual_total > MAX_EXPANDED:
                            raise DomainError("XMIND_ZIP_BOMB", "Actual expanded size exceeds limit", 422)
                        if name in {"content.json", "content.xml"}:
                            chunks.append(chunk)
                    if actual != info.file_size:
                        raise DomainError("XMIND_SIZE_MISMATCH", "Declared entry size is wrong", 422)
                    if name in {"content.json", "content.xml"}:
                        if content is not None:
                            raise DomainError("XMIND_TEMPLATE_AMBIGUOUS", "Only one content entry is accepted", 422)
                        content = b"".join(chunks)
    except (zipfile.BadZipFile, RuntimeError, UnicodeDecodeError) as error:
        raise DomainError("INVALID_XMIND", "Malformed XMind archive", 422) from error
    if content is None:
        raise DomainError("XMIND_TEMPLATE_REQUIRED", "content.json or content.xml is required", 422)
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DomainError("INVALID_XMIND", "XMind content must be UTF-8", 422) from error
    if DANGEROUS.search(text):
        raise DomainError("XMIND_ACTIVE_CONTENT", "Active content or external links are forbidden", 422)
    if text.lstrip().startswith(("[", "{")):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            raise DomainError("INVALID_XMIND", "Malformed XMind JSON", 422) from error
        _json_depth(parsed)
        return _normalize_json(parsed)
    return _normalize_xml(content)
