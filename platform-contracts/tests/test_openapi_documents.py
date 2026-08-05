"""Dependency-free baseline validation for every OpenAPI YAML document."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


class OpenApiDocumentTests(unittest.TestCase):
    def test_every_openapi_document_has_required_structure(self) -> None:
        files = list(ROOT.glob("*-service/openapi/*.yaml")) + list(
            (ROOT / "platform-contracts" / "openapi").glob("*.yaml")
        )
        self.assertGreaterEqual(len(files), 5)
        for path in files:
            with self.subTest(path=path):
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(document, dict)
                self.assertEqual(document.get("openapi"), "3.1.0")
                self.assertIsInstance(document.get("info"), dict)
                self.assertIsInstance(document.get("paths"), dict)
                self.assertTrue(document["info"].get("title"))
                self.assertTrue(document["info"].get("version"))
