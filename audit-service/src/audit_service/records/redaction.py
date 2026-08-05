"""Audit sensitive-data rejection and bounded redaction."""
import json
import re

SENSITIVE = re.compile(r"password|token|secret|authorization|cookie|otp", re.IGNORECASE)


def validate_and_redact(value: dict[str, object]) -> dict[str, object]:
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded.encode()) > 65536:
        raise ValueError("AUDIT_EVENT_TOO_LARGE")

    def walk(item: object) -> object:
        if isinstance(item, dict):
            for key in item:
                if SENSITIVE.search(str(key)):
                    raise ValueError("SENSITIVE_FIELD_REJECTED")
            return {str(k): walk(v) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        return item

    return walk(value)  # type: ignore[return-value]
