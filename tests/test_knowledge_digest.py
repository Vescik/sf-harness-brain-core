from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts.knowledge_digest import canonical, canonical_digest

ROOT = Path(__file__).resolve().parents[1]


class DigestStabilityTests(unittest.TestCase):
    """Pinned bytes, not properties. canonical_digest() values are persisted in entry
    filenames, reviewedContentDigest, sourceTreeDigest, org-usage sectionDigest and the
    approval ledgers — a serialization "improvement" here silently revokes every approved
    Knowledge Entry. These constants were computed at the P0 relocation (2026-08-03) and
    must never change."""

    def test_canonical_form_is_sorted_compact_and_utf8(self) -> None:
        value = {"b": 1, "a": [1, 2], "c": {"y": None, "x": True}}
        self.assertEqual('{"a":[1,2],"b":1,"c":{"x":true,"y":null}}', canonical(value))
        # ensure_ascii=False is load-bearing: non-ASCII stays raw UTF-8, not \u-escaped.
        self.assertEqual('{"n":1.5,"name":"Zażółć"}', canonical({"name": "Zażółć", "n": 1.5}))

    def test_digest_values_are_pinned(self) -> None:
        pins = {
            "sha256:9c92cbb0517b3291cd4b4297c196c8535294e6b525e6c66dbd3db6c3701f7b0e": {
                "b": 1,
                "a": [1, 2],
                "c": {"y": None, "x": True},
            },
            "sha256:4857a64a3916eefab4adf4838dc58837c4c6ba80e9b42abfef06c6f2cafe7e75": {
                "name": "Zażółć",
                "n": 1.5,
            },
            "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945": [],
            "sha256:717b84c649498e5c301871fc2496d800f7fbf5827996a720349bde984b537966": "Flow:c:HarnessAlphaRouter",
        }
        for expected, value in pins.items():
            self.assertEqual(expected, canonical_digest(value))

    def test_key_order_cannot_change_the_digest(self) -> None:
        self.assertEqual(canonical_digest({"a": 1, "b": 2}), canonical_digest({"b": 2, "a": 1}))


class DependencyDirectionTests(unittest.TestCase):
    """The claim registry is retired (v1 retirement P2b). Nothing in scripts/ may import
    it again — a reintroduced module would resurrect the dependency this pin ended."""

    IMPORT_RE = re.compile(r"^\s*(from|import)\s+(scripts\.)?knowledge_registry\b", re.MULTILINE)

    def test_no_script_imports_the_retired_registry(self) -> None:
        for path in sorted((ROOT / "scripts").glob("*.py")):
            with self.subTest(script=path.name):
                self.assertIsNone(self.IMPORT_RE.search(path.read_text(encoding="utf-8")))

    def test_the_registry_module_stays_deleted(self) -> None:
        self.assertFalse((ROOT / "scripts/knowledge_registry.py").exists())

    def test_store_uses_the_one_digest_implementation(self) -> None:
        from scripts import knowledge_store

        self.assertIs(canonical_digest, knowledge_store.canonical_digest)
