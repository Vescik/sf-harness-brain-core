"""Pins the reference-kind vocabulary shared by the extractor and the registry.

`scripts/force_app_knowledge.py` emits usage references; `scripts/knowledge_registry.py`
classifies the same kinds into FIELD/OBJECT/INVOKE/EXTERNAL sets to derive usesObjects,
usesFields, and --invokes query results. The two vocabularies live in different files on
purpose (the CLIs run standalone), so this contract is the only thing preventing drift:
a kind added to the extractor without a registry classification would silently vanish
from every usage query.
"""

from __future__ import annotations

import unittest

from scripts import force_app_knowledge
from scripts import knowledge_registry


# Kinds the extractor declares but the crawl's object-association set intentionally
# excludes, with the reason. Keys must stay in ALL_REF_KINDS.
INTENTIONALLY_NOT_OBJECT_KINDS = {
    "subflow": "target names another Flow",
    "action": "target names an invocable action",
    "apex-method": "target names an Apex method",
    "apex-controller": "target names an Apex class",
    "invokes-apex": "target names an Apex class",
    "invokes-class": "target names an Apex class",
    "related-list": "target names a related list, not an object",
    "uses-value-set": "target names a global/standard value set",
    "sends-alert": "target names an Object.AlertName workflow alert",
    "uses-template": "target names an EmailTemplate folder/name",
    "uses-named-credential": "target names a NamedCredential",
    "callout-endpoint": "target is an endpoint hostname",
    "uses-workflow-action": "target names an Object.ActionName workflow action",
    "uses-business-process": "target names an Object.BusinessProcess component",
    "uses-matching-rule": "target names an Object.MatchingRule component",
    "uses-label": "target names a CustomLabel",
    "embeds-component": "target names a child component bundle",
    "displays-component": "target names a rendered component",
    "launches-flow": "target names a Flow",
    "overrides-view": "target names the assigned FlexiPage",
    "grants-class-access": "target names an Apex class",
    "grants-custom-permission": "target names a CustomPermission",
    "grants-record-type": "target names an Object.RecordType component",
    "grants-flow-access": "target names a Flow",
    "grants-user-permission": "target is a system-permission string",
    "assigns-layout": "target names a Layout",
    "shares-with": "target is an org principal (role/group/queue)",
    "assigns-to": "target names a Queue component",
    "uses-external-credential": "target names an ExternalCredential",
    "references-auth-provider": "target names an AuthProvider",
    "grants-to-profile": "target names a Profile",
    "grants-to-permission-set": "target names a PermissionSet",
    "references-custom-permission": "target names a CustomPermission",
    "includes-permission-set": "target names a PermissionSet",
    "mutes-permission-set": "target names a MutingPermissionSet",
    "reports-to": "target names the parent Role",
}


class KindContractTests(unittest.TestCase):
    def registry_sets(self) -> dict[str, frozenset[str]]:
        return {
            "FIELD_REF_KINDS": knowledge_registry.FIELD_REF_KINDS,
            "OBJECT_REF_KINDS": knowledge_registry.OBJECT_REF_KINDS,
            "INVOKE_REF_KINDS": knowledge_registry.INVOKE_REF_KINDS,
            "EXTERNAL_REF_KINDS": knowledge_registry.EXTERNAL_REF_KINDS,
        }

    def test_every_extractor_kind_classified_exactly_once(self) -> None:
        sets = self.registry_sets()
        for kind in sorted(force_app_knowledge.ALL_REF_KINDS):
            memberships = [name for name, kinds in sets.items() if kind in kinds]
            self.assertEqual(
                1,
                len(memberships),
                f"kind {kind!r} must be classified in exactly one registry set, "
                f"found in: {memberships or 'none'}",
            )

    def test_registry_has_no_unknown_kinds(self) -> None:
        classified = frozenset().union(*self.registry_sets().values())
        unknown = classified - force_app_knowledge.ALL_REF_KINDS
        self.assertEqual(
            frozenset(),
            unknown,
            f"registry classifies kinds the extractor never emits: {sorted(unknown)}",
        )

    def test_crawl_object_kinds_match_registry_field_and_object_sets(self) -> None:
        expected = (
            knowledge_registry.FIELD_REF_KINDS | knowledge_registry.OBJECT_REF_KINDS
        )
        self.assertEqual(
            expected,
            force_app_knowledge.OBJECT_REF_KINDS,
            "the extractor's crawl object-association set must equal the registry's "
            "FIELD ∪ OBJECT classification (a kind whose target names an object heads "
            "both); document intentional exceptions in this test if one ever appears",
        )

    def test_intentional_exclusions_are_declared_kinds(self) -> None:
        for kind in INTENTIONALLY_NOT_OBJECT_KINDS:
            self.assertIn(kind, force_app_knowledge.ALL_REF_KINDS)
            self.assertNotIn(kind, force_app_knowledge.OBJECT_REF_KINDS)

    def test_all_kinds_is_complete_over_extractor_sets(self) -> None:
        self.assertLessEqual(
            force_app_knowledge.OBJECT_REF_KINDS, force_app_knowledge.ALL_REF_KINDS
        )
        self.assertLessEqual(
            force_app_knowledge.HEURISTIC_REF_KINDS, force_app_knowledge.ALL_REF_KINDS
        )
        self.assertEqual(
            force_app_knowledge.ALL_REF_KINDS,
            force_app_knowledge.OBJECT_REF_KINDS
            | frozenset(INTENTIONALLY_NOT_OBJECT_KINDS),
            "ALL_REF_KINDS must be exactly the object-association kinds plus the "
            "documented non-object kinds",
        )


if __name__ == "__main__":
    unittest.main()
