"""Contract guards for requirement, test, defect, and traceability domains."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).parents[1] / "schemas"

DOMAIN_SCHEMAS = (
    "requirement-events.v1.schema.json",
    "tp-events.v1.schema.json",
    "td-events.v1.schema.json",
    "traceability-events.v1.schema.json",
    "reference-check.v1.schema.json",
    "automation-result.v1.schema.json",
)
FORBIDDEN_EVENT_FIELDS = {"description", "prompt", "test_data", "reproduction_steps", "attachment_url", "token", "cookie", "secret"}


def test_domain_schemas_are_strict_and_valid() -> None:
    for name in DOMAIN_SCHEMAS:
        schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"].endswith("2020-12/schema")


def test_event_contracts_do_not_define_sensitive_payload_fields() -> None:
    for name in DOMAIN_SCHEMAS[:4]:
        text = (SCHEMA_DIR / name).read_text(encoding="utf-8").lower()
        assert all(f'"{field}"' not in text for field in FORBIDDEN_EVENT_FIELDS)


def test_trace_link_types_are_an_allowlist() -> None:
    schema = json.loads((SCHEMA_DIR / "traceability-events.v1.schema.json").read_text(encoding="utf-8"))
    link_types = schema["properties"]["link_type"]["enum"]
    assert "covered_by" in link_types
    assert "fixed_by" in link_types
    assert len(link_types) == len(set(link_types))


def test_automation_json_has_hard_item_limit() -> None:
    schema = json.loads((SCHEMA_DIR / "automation-result.v1.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["results"]["maxItems"] == 10_000
