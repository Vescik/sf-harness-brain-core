"""Storage-family layout pins (plan 2026-08-06, Z4).

The family tree is navigation, never evidence: these tests pin the routing contract
itself — every registered type routes to exactly one family, objects-family members split
on the first dot, and the retired flat layout must never quietly come back.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import knowledge_store as store


class FamilyRegistryPinTests(unittest.TestCase):
    """The one table in code and the live PROFILES registry may never drift."""

    def test_every_registered_profile_has_exactly_one_family(self) -> None:
        for metadata_type in store.PROFILES:
            self.assertIn(metadata_type, store.FAMILY_BY_TYPE, metadata_type)

    def test_no_family_entry_for_an_unregistered_type(self) -> None:
        self.assertEqual(set(store.FAMILY_BY_TYPE), set(store.PROFILES))

    def test_member_dirs_are_exactly_the_objects_family_minus_the_root(self) -> None:
        objects_members = {
            name for name, family in store.FAMILY_BY_TYPE.items()
            if family == "objects" and name != "CustomObject"
        }
        self.assertEqual(set(store.OBJECT_MEMBER_DIRS), objects_members)

    def test_member_dir_names_are_distinct(self) -> None:
        dirs = list(store.OBJECT_MEMBER_DIRS.values())
        self.assertEqual(len(dirs), len(set(dirs)))


class EntryPathRoutingTests(unittest.TestCase):
    def relative(self, metadata_type: str, namespace: str | None, full_name: str) -> str:
        return store.relative_path(store.entry_path(metadata_type, namespace, full_name))

    def test_every_registered_type_routes_under_its_family(self) -> None:
        for metadata_type, family in store.FAMILY_BY_TYPE.items():
            if family == "objects" and metadata_type != "CustomObject":
                full_name = "Obj__c.Member__c"
            else:
                full_name = "Sample_Name"
            with self.subTest(metadata_type=metadata_type):
                rel = self.relative(metadata_type, None, full_name)
                self.assertTrue(
                    rel.startswith(f".ai/knowledge/artifacts/{family}/"), rel
                )

    def test_object_root_is_the_fixed_object_leaf(self) -> None:
        self.assertEqual(
            ".ai/knowledge/artifacts/objects/c/Invoice__c/object.md",
            self.relative("CustomObject", None, "Invoice__c"),
        )

    def test_every_member_type_routes_into_its_directory(self) -> None:
        expected = {
            "CustomField": "fields",
            "ValidationRule": "validation-rules",
            "RecordType": "record-types",
            "BusinessProcess": "business-processes",
            "DuplicateRule": "duplicate-rules",
            "MatchingRule": "matching-rules",
        }
        self.assertEqual(expected, store.OBJECT_MEMBER_DIRS)
        for metadata_type, directory in expected.items():
            with self.subTest(metadata_type=metadata_type):
                self.assertEqual(
                    f".ai/knowledge/artifacts/objects/c/Invoice__c/{directory}/Member__c.md",
                    self.relative(metadata_type, None, "Invoice__c.Member__c"),
                )

    def test_typical_family_shape_is_family_type_namespace_name(self) -> None:
        self.assertEqual(
            ".ai/knowledge/artifacts/automation/Flow/c/Invoice_After_Save.md",
            self.relative("Flow", None, "Invoice_After_Save"),
        )

    def test_namespaced_member_keeps_the_package_prefix_per_segment(self) -> None:
        self.assertEqual(
            ".ai/knowledge/artifacts/objects/KimbleOne/KimbleOne__DeliveryGroup__c"
            "/fields/KimbleOne__Rate__c.md",
            self.relative(
                "CustomField", "KimbleOne", "KimbleOne__DeliveryGroup__c.KimbleOne__Rate__c"
            ),
        )

    def test_standard_object_member_routes_like_any_other(self) -> None:
        self.assertEqual(
            ".ai/knowledge/artifacts/objects/c/Account/duplicate-rules/Std_Dup.md",
            self.relative("DuplicateRule", None, "Account.Std_Dup"),
        )

    def test_member_dot_is_a_separator_not_an_escape(self) -> None:
        # Under the flat layout the identity dot was %2E-escaped into the leaf name; the
        # object tree spends it as a real directory boundary instead.
        self.assertNotIn("%2E", self.relative("CustomField", None, "Invoice__c.Amount__c"))

    def test_object_directory_is_identical_for_root_and_members(self) -> None:
        root = store.entry_path("CustomObject", None, "Invoice__c")
        member = store.entry_path("CustomField", None, "Invoice__c.Amount__c")
        self.assertEqual(root.parent, member.parent.parent)

    def test_dot_in_a_non_objects_name_still_escapes(self) -> None:
        # CustomMetadata full names carry a dot that is NOT an object/member split.
        self.assertEqual(
            ".ai/knowledge/artifacts/configuration/CustomMetadata/c/Fee_Config%2EStandard.md",
            self.relative("CustomMetadata", None, "Fee_Config.Standard"),
        )

    def test_unicode_and_reserved_names_still_route(self) -> None:
        for metadata_type, full_name in [
            ("Flow", "Zażółć_gęślą_jaźń"),
            ("Flow", "CON"),
            ("CustomField", "Obj__c.CON"),
        ]:
            with self.subTest(full_name=full_name):
                path = store.entry_path(metadata_type, None, full_name)
                self.assertTrue(str(path).endswith(".md"))

    def test_worst_case_realistic_paths_fit_the_budget(self) -> None:
        # Salesforce caps API names at 40 chars + __c and namespaces at 15 chars; the longest
        # family prefix is configuration/ and the deepest tree is an objects member.
        ns = "A" * 15
        obj = f"{ns}__{'B' * 40}__c"
        member = f"{ns}__{'C' * 40}__c"
        for metadata_type, namespace, full_name in [
            ("ExternalServiceRegistration", ns, f"{ns}__{'D' * 40}"),
            ("CustomField", ns, f"{obj}.{member}"),
            ("CustomMetadata", ns, f"{ns}__{'D' * 40}.{ns}__{'E' * 40}"),
        ]:
            with self.subTest(metadata_type=metadata_type):
                rel = store.relative_path(store.entry_path(metadata_type, namespace, full_name))
                self.assertLessEqual(len(rel), store.PATH_BUDGET, rel)

    def test_a_type_without_a_family_fails_closed(self) -> None:
        with self.assertRaises(store.StoreError):
            store.entry_path("EmailTemplateFolder", None, "Whatever")

    def test_a_member_type_without_its_dot_fails_closed(self) -> None:
        for full_name in ["NoDotHere", ".LeadingDot", "TrailingDot."]:
            with self.subTest(full_name=full_name):
                with self.assertRaises(store.StoreError):
                    store.entry_path("CustomField", None, full_name)


class IdentityFromEntryPathTests(unittest.TestCase):
    def test_round_trip_holds_for_every_type_and_namespace(self) -> None:
        for metadata_type in store.PROFILES:
            for namespace in (None, "KimbleOne"):
                if store.FAMILY_BY_TYPE[metadata_type] == "objects" and metadata_type != "CustomObject":
                    full_name = "Obj__c.Member__c"
                else:
                    full_name = "Sample_Name"
                with self.subTest(metadata_type=metadata_type, namespace=namespace):
                    path = store.entry_path(metadata_type, namespace, full_name)
                    self.assertEqual(
                        store.identity_of(metadata_type, namespace, full_name),
                        store.identity_from_entry_path(path),
                    )

    def test_the_flat_layout_is_not_supported(self) -> None:
        # The retirement pin: bringing back artifacts/<Type>/<ns>/<name>.md — or quietly
        # serving both shapes — must fail this test.
        flat = store.ARTIFACTS_ROOT / "Flow" / "c" / "Old_Flat.md"
        self.assertIsNone(store.identity_from_entry_path(flat))

    def test_the_path_budget_still_fails_closed_at_the_new_depth(self) -> None:
        # Two digest-truncated ~109-char segments under objects/ overflow the 200-char
        # budget; the guard must refuse, not silently shorten.
        with self.assertRaises(store.StoreError):
            store.entry_path("ValidationRule", None, f"{'X' * 400}.{'Y' * 400}")

    def test_unrecognized_shapes_yield_none_never_a_wrong_identity(self) -> None:
        root = store.ARTIFACTS_ROOT
        for path in [
            root / "objects" / "c" / "Invoice__c" / "fields" / "A.B.md",
            root / "objects" / "c" / "Invoice__c" / "unknown-dir" / "X.md",
            root / "objects" / "c" / "Invoice__c" / "loose.md",
            root / "objects" / "c" / "object.md",
            root / "automation" / "ApexClass" / "c" / "Wrong_Family.md",
            root / "code" / "ApexClass" / "c" / "Has%2EEscape.md",
            root / "objects" / "c" / "Invoice__c" / "fields" / "Deep" / "X.md",
            root / "shared" / "loose.md",
        ]:
            with self.subTest(path=str(path)):
                self.assertIsNone(store.identity_from_entry_path(path))

    def test_case_twin_paths_disambiguate_by_round_trip(self) -> None:
        lower = store.entry_path("Flow", None, "invoice_flow")
        upper = store.entry_path("Flow", None, "INVOICE_FLOW")
        self.assertNotEqual(lower, upper)
        self.assertEqual("Flow:c:invoice_flow", store.identity_from_entry_path(lower))
        self.assertEqual("Flow:c:INVOICE_FLOW", store.identity_from_entry_path(upper))


if __name__ == "__main__":
    unittest.main()
