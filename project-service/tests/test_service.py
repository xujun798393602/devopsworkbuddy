import pytest

from project_service.projects.service import create_request_hash, normalize_create_payload
from project_service.shared.errors import ValidationError


def test_canonical_hash_normalizes_unicode_and_whitespace() -> None:
    left = normalize_create_payload({"name": "  Cafe\u0301 ", "description": " x "}, "actor")
    right = normalize_create_payload({"description": "x", "name": "Café"}, "actor")
    assert create_request_hash(left) == create_request_hash(right)


def test_actor_is_part_of_default_owner_hash() -> None:
    first = normalize_create_payload({"name": "X"}, "actor-a")
    second = normalize_create_payload({"name": "X"}, "actor-b")
    assert create_request_hash(first) != create_request_hash(second)


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"name": "X", "unknown": True}, "unknown"),
        ({"name": 1}, "name"),
        ({"name": "X", "description": []}, "description"),
        ({"name": "X", "owner_id": False}, "owner_id"),
        ({"name": "X", "owner_id": "  "}, "owner_id"),
    ],
)
def test_strict_payload_validation(payload: dict[str, object], field: str) -> None:
    with pytest.raises(ValidationError) as captured:
        normalize_create_payload(payload, "actor")
    assert captured.value.errors
    assert captured.value.errors[0]["field"] == field
