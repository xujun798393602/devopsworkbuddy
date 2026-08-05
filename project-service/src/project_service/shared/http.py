"""HTTP contract helpers."""

from __future__ import annotations

import base64
import json

from flask import Request

from project_service.shared.errors import ValidationError


def require_idempotency_key(request: Request) -> str:
    """Return a valid required idempotency key."""
    key = request.headers.get("Idempotency-Key", "").strip()
    if not 1 <= len(key) <= 255:
        raise ValidationError("Idempotency-Key header must contain 1 to 255 characters")
    return key


def require_if_match(request: Request) -> int:
    """Parse a strong numeric If-Match ETag."""
    value = request.headers.get("If-Match", "")
    if len(value) < 3 or not value.startswith('"') or not value.endswith('"'):
        raise ValidationError('If-Match must be a quoted positive integer, for example "1"')
    try:
        version = int(value[1:-1])
    except ValueError as error:
        raise ValidationError("If-Match must contain a positive integer") from error
    if version < 1:
        raise ValidationError("If-Match must contain a positive integer")
    return version


def parse_limit(request: Request) -> int:
    """Parse the standard page limit."""
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError as error:
        raise ValidationError("limit must be an integer") from error
    if not 1 <= limit <= 200:
        raise ValidationError("limit must be between 1 and 200")
    return limit


def encode_cursor(project_id: str, created_at: str, resource_id: str) -> str:
    """Encode a project-scoped stable opaque cursor."""
    raw = json.dumps([project_id, created_at, resource_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str | None, project_id: str) -> tuple[str, str] | None:
    """Decode and validate a project-scoped stable opaque cursor."""
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError("cursor is invalid") from error
    if (
        not isinstance(data, list)
        or len(data) != 3
        or not all(isinstance(item, str) for item in data)
        or data[0] != project_id
    ):
        raise ValidationError("cursor is invalid")
    return data[1], data[2]
