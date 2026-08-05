import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).parents[1] / "schemas"


class ContractSchemaTests(unittest.TestCase):
    def test_supported_python_runtime(self) -> None:
        self.assertGreaterEqual(sys.version_info[:2], (3, 12))
        self.assertLess(sys.version_info[:2], (3, 14))
        self.assertIn(sys.implementation.cache_tag, {"cpython-312", "cpython-313"})

    def test_all_schemas_are_valid_draft_2020_12(self) -> None:
        files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        self.assertGreaterEqual(len(files), 7)
        for schema_file in files:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)

    def test_envelope_backwards_compatible_and_platform_scoped(self) -> None:
        schema = json.loads((SCHEMA_DIR / "event-envelope.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["project_id"]["type"], ["string", "null"])
        actor_ref = schema["properties"]["actor"]["$ref"]
        self.assertIn("identity-context", actor_ref)

    def test_jwt_algorithm_is_not_part_of_untrusted_claims(self) -> None:
        schema = json.loads((SCHEMA_DIR / "identity-context.schema.json").read_text(encoding="utf-8"))
        self.assertNotIn("alg", schema["properties"])


if __name__ == "__main__":
    unittest.main()
