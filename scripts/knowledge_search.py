"""Knowledge Entry search (T08b): typed retrieval over one-file Knowledge Entries.

Implements the retrieval design frozen in docs/knowledge-one-file-contract.md and
docs/evidence-to-analyse.md §25: scope and trust are applied BEFORE ranking, results are
compact projections that always explain themselves, and the generated index is a
disposable cache — never a second source of truth.

Storage: `.cache/knowledge-search/gen-<digest>/` immutable generations plus a small
atomic `current.json` pointer. The cache is git-ignored, never approved, never citable;
every hit cites the canonical entry path with its digests.

Freshness is fail-closed: if the committed entry set no longer matches the generation the
pointer names, queries refuse with INDEX STALE rather than answering from a stale index.

Ranking never overrides authority: lifecycle lane, namespace/package scope, metadata type,
and typed facets are hard filters; BM25F only orders what survives them. Draft entries are
returned in a separate lane and never interleave with approved results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from scripts import knowledge_store as store
    from scripts import relation_kinds
    from scripts.text_analysis import ANALYZER_VERSION, analyze, fold_diacritics
except ModuleNotFoundError:  # invoked as `python scripts/knowledge_search.py`
    import knowledge_store as store  # type: ignore
    import relation_kinds  # type: ignore
    from text_analysis import ANALYZER_VERSION, analyze, fold_diacritics  # type: ignore

# 1 -> 2 (2026-08-03): projections gained the orgUsage metadata block (orgKey/environment/
# observedAt/expiresAt only — probe values NEVER enter fields or facets). The manifest check
# self-invalidates version-1 caches; no test pins the value.
INDEX_SCHEMA_VERSION = 2
POLICY_VERSION = "1.0.0"

# BM25F field weights (docs/evidence-to-analyse.md §25.8.3). Values are a starting point to
# be tuned on the golden set; identity and intentional-error text outrank everything else.
FIELD_WEIGHTS = {
    "identity": 6.0,
    "intentionalError": 6.0,
    "keyword": 3.0,
    "label": 3.0,
    "purpose": 2.0,
    "attribute": 1.5,
    "relationTarget": 1.0,
    "sourcePath": 0.2,
}
LEXICAL_CANDIDATE_CAP = 2000
# One vocabulary, per-command values. A single shared depth cannot serve both: reverse impact
# saturates fast, while a feature tree needs trigger -> handler -> queueable -> event.
DEPTH_LIMITS = {"impact": 2, "context": 1}
# §9's last open item: a pathological walk must terminate on more than a node count, so a
# wall-clock limit sits alongside the node/fanout caps. The values are adopted constants:
# they were originally derived from knowledge_benchmark measurements on a synthetic corpus,
# and kept as-is when that benchmark was retired (2026-08-05, decisions log) — the corpus was
# still near-empty, so the measurement added no information a smoke bound would not.
#
# Depth is deliberately NOT here: R7 fixes depth per command as a SEMANTIC requirement
# (DEPTH_LIMITS above), and no measurement has standing to move it.
TRAVERSAL_LIMITS = {"maxNodes": 5000, "maxFanout": 2000, "maxSeconds": 2.0}

# The plan's own list, verbatim from §9: "node/fanout/row/time traversal limits". Named here so a
# test can count THE PLAN'S set instead of whatever this module happens to enforce — three of the
# four were implemented and the fourth was missing for exactly as long as nothing counted them.
# Keys are the `limitsHit` tokens a caller reads; `row` maps to no TRAVERSAL_LIMITS key because
# it is `--top`, applied by each command to its own rows after the walk rather than inside it.
PLAN_TRAVERSAL_LIMITS = {
    "nodes": "maxNodes",
    "fanout": "maxFanout",
    "top": None,
    "time": "maxSeconds",
}
IMPACT_TOP_DEFAULT = 50
EXPLAIN_TOP_DEFAULT = 50
# The relation kind that carries composition. Named once so `parts` and the tree agree.
CONTAINMENT_KIND = "belongs-to"
BM25_K1 = 1.2
BM25_B = 0.75
# A query token in at least this share of the corpus cannot discriminate between entries.
# Corpus-derived on purpose: `saturated` is a statement about THIS store, not about English,
# so there is no stopword list to maintain and no ANALYZER_VERSION bump to pay. A share is
# meaningless over a handful of documents — in a 1-entry store EVERY matched term hits 100%
# and a bootstrap store would be unsearchable — so below the corpus floor nothing saturates.
DF_SATURATION = 0.5
DF_SATURATION_MIN_CORPUS = 4

ESTABLISHED_STATES = ("approved-current",)
ALL_LANES = (
    "approved-current",
    "approved-drifted",
    "draft",
    "revoked",
    "scope-mismatch",
    "unsupported-profile",
    "not-effective",
)

GLOBAL_FACETS = {
    "metadataType": "string",
    "family": "string",
    "fullName": "string",
    "namespace": "string",
    "packageVersionId": "string",
    "sourceApiVersion": "string",
    "sourcePath": "string",
    "profile.id": "string",
    "profile.version": "string",
    "effectiveState": "string",
    "extractionCoverage.typeFacts": "string",
}
PROFILE_FACETS = {
    "Flow": {
        "flow.processType": "string",
        "flow.status": "string",
        "flow.trigger.object": "string",
        "flow.trigger.type": "string",
        "flow.recordTriggerType": "string",
        "flow.hasIntentionalCustomError": "boolean",
        "flow.intentionalError.placement": "string",
        "flow.intentionalError.field": "string",
        "flow.intentionalError.usesLabel": "boolean",
    },
    "ApexClass": {
        "apex.kind": "string",
        "apex.sharing": "string",
        "apex.isTest": "boolean",
        "apex.apiVersion": "string",
        "apex.status": "string",
        "apex.superclass": "string",
        "apex.interfaces": "string",
        "apex.annotations": "string",
    },
    "ApexTrigger": {
        "apex.kind": "string",
        "apex.isTest": "boolean",
        "apex.apiVersion": "string",
        "trigger.object": "string",
        "trigger.events": "string",
    },
    "ValidationRule": {
        "validationRule.object": "string",
        "validationRule.active": "boolean",
        "validationRule.errorDisplayField": "string",
    },
    "PermissionSet": {
        "permissionSet.label": "string",
        "permissionSet.license": "string",
        "permissionSet.systemPermissions": "string",
        "permissionSet.objectPermissionCount": "number",
        "permissionSet.fieldPermissionCount": "number",
        "permissionSet.referencesTruncated": "boolean",
        "permissionSet.truncatedFamilies": "string",
    },
    "CustomObject": {
        "object.kind": "string",
        "object.sharingModel": "string",
        "object.deploymentStatus": "string",
        "object.eventType": "string",
        "object.customSettingsType": "string",
    },
    "RecordType": {
        "recordType.object": "string",
        "recordType.active": "boolean",
    },
    "CustomMetadata": {
        "customMetadata.type": "string",
        "customMetadata.protected": "boolean",
    },
    "LightningComponentBundle": {
        "lwc.isExposed": "boolean",
        "lwc.targets": "string",
    },
    "CustomField": {
        "field.object": "string",
        "field.type": "string",
        "field.required": "boolean",
        "field.unique": "boolean",
        "field.externalId": "boolean",
        "field.encrypted": "boolean",
        "field.referenceTo": "string",
        "field.controllingField": "string",
        "field.length": "number",
        "field.precision": "number",
        "field.scale": "number",
    },
    "FieldSet": {
        "fieldSet.object": "string",
        "fieldSet.label": "string",
    },
    "CompactLayout": {
        "compactLayout.object": "string",
        "compactLayout.label": "string",
    },
    "BusinessProcess": {
        "businessProcess.object": "string",
        "businessProcess.active": "boolean",
        "businessProcess.lifecycleField": "string",
    },
    "WebLink": {
        "webLink.object": "string",
        "webLink.linkType": "string",
        "webLink.isJavascript": "boolean",
    },
    "DuplicateRule": {
        "duplicateRule.object": "string",
        "duplicateRule.active": "boolean",
        "duplicateRule.actionOnInsert": "string",
        "duplicateRule.actionOnUpdate": "string",
    },
    "MatchingRule": {
        "matchingRule.object": "string",
        "matchingRule.status": "string",
    },
    "Queue": {
        "queue.name": "string",
        "queue.servesObjects": "string",
        "queue.doesSendEmailToMembers": "boolean",
    },
    "Role": {
        "role.label": "string",
        "role.caseAccessLevel": "string",
        "role.opportunityAccessLevel": "string",
    },
    "DelegateGroup": {
        "delegateGroup.label": "string",
        "delegateGroup.loginAccess": "boolean",
    },
    "PermissionSetGroup": {
        "permissionSetGroup.label": "string",
        "permissionSetGroup.status": "string",
        "permissionSetGroup.permissionSetCount": "number",
    },
    "StaticResource": {
        "staticResource.contentType": "string",
        "staticResource.cacheControl": "string",
    },
    "PlatformEventChannel": {
        "platformEventChannel.channelType": "string",
        "platformEventChannel.label": "string",
    },
    "PlatformEventChannelMember": {
        "platformEventChannelMember.eventChannel": "string",
        "platformEventChannelMember.selectedEntity": "string",
    },
    "GlobalValueSet": {
        "valueSet.sorted": "boolean",
        "valueSet.valueCount": "number",
        "valueSet.masterLabel": "string",
    },
    "StandardValueSet": {
        "valueSet.sorted": "boolean",
        "valueSet.valueCount": "number",
        "valueSet.masterLabel": "string",
    },
    "CustomLabel": {
        "customLabel.language": "string",
        "customLabel.protected": "boolean",
        "customLabel.categories": "string",
    },
    "CustomTab": {
        "customTab.tabKind": "string",
        "customTab.label": "string",
    },
    "CustomApplication": {
        "customApplication.navType": "string",
        "customApplication.uiType": "string",
        "customApplication.hasUtilityBar": "boolean",
    },
    "FlowDefinition": {
        "flowDefinition.active": "boolean",
        "flowDefinition.activeVersionNumber": "number",
    },
    "PathAssistant": {
        "pathAssistant.object": "string",
        "pathAssistant.active": "boolean",
        "pathAssistant.recordType": "string",
    },
    "ListView": {
        "listView.object": "string",
        "listView.queue": "string",
        "listView.filterScope": "string",
    },
    "ReportType": {
        "reportType.baseObject": "string",
        "reportType.category": "string",
        "reportType.deployed": "boolean",
    },
    "SharingRules": {
        "sharingRules.object": "string",
        "sharingRules.criteriaRuleCount": "number",
        "sharingRules.ownerRuleCount": "number",
    },
    "QuickAction": {
        "quickAction.object": "string",
        "quickAction.actionType": "string",
    },
    "MutingPermissionSet": {
        "mutingPermissionSet.label": "string",
        "mutingPermissionSet.mutedSystemPermissions": "string",
        "mutingPermissionSet.fieldPermissionCount": "number",
    },
    "Dashboard": {
        "dashboard.folder": "string",
        "dashboard.runningUserPolicy": "string",
    },
    "EmailTemplate": {
        "emailTemplate.folder": "string",
        "emailTemplate.templateType": "string",
        "emailTemplate.available": "boolean",
    },
    "AuraDefinitionBundle": {
        "aura.extends": "string",
        "aura.implements": "string",
    },
    # The nine integration types share the salesforce.integration profile and one facet set.
    **{
        metadata_type: {
            "integration.endpointHost": "string",
            "integration.label": "string",
            "integration.isActive": "boolean",
        }
        for metadata_type in (
            "NamedCredential",
            "ExternalCredential",
            "RemoteSiteSetting",
            "ExternalDataSource",
            "ExternalServiceRegistration",
            "ConnectedApp",
            "AuthProvider",
            "CspTrustedSite",
            "CorsWhitelistOrigin",
        )
    },
    "Profile": {
        "profile.label": "string",
        "profile.custom": "boolean",
        "profile.userLicense": "string",
    },
    "Layout": {
        "layout.object": "string",
        "layout.fieldCount": "number",
    },
    "FlexiPage": {
        "flexiPage.pageType": "string",
        "flexiPage.object": "string",
        "flexiPage.template": "string",
    },
    "Workflow": {
        "workflow.object": "string",
        "workflow.ruleCount": "number",
        "workflow.activeRuleCount": "number",
    },
    # The three routing-rule containers share the salesforce.routing-rules profile
    # and one facet set.
    **{
        metadata_type: {
            "routingRules.object": "string",
            "routingRules.ruleCount": "number",
        }
        for metadata_type in ("AssignmentRules", "AutoResponseRules", "EscalationRules")
    },
    "ApprovalProcess": {
        "approvalProcess.object": "string",
        "approvalProcess.active": "boolean",
        "approvalProcess.stepCount": "number",
    },
    "Report": {
        "report.reportType": "string",
        "report.folder": "string",
        "report.format": "string",
    },
    # ApexPage and ApexComponent share the salesforce.visualforce profile and one facet set.
    **{
        metadata_type: {
            "visualforce.standardController": "string",
            "visualforce.controller": "string",
            "visualforce.apiVersion": "string",
        }
        for metadata_type in ("ApexPage", "ApexComponent")
    },
}
FACET_OPERATORS = ("eq", "in", "exists", "prefix", "has", "gte", "lte")


class SearchError(RuntimeError):
    """Fail-closed search error; the message names the actionable reason."""


def cache_root() -> Path:
    return store.ROOT / ".cache/knowledge-search"


# --- analyzer (Unicode + Salesforce identifiers) ---------------------------------------

# Merge fields collapse to a single visible sentinel so two messages that differ only in
# their runtime variables share a fingerprint, while a message with no variable at all
# stays distinct. U+FFFC (OBJECT REPLACEMENT CHARACTER) can never occur in Flow source.
MERGE_PLACEHOLDER = "\ufffc"


def message_fingerprint(message: str) -> str:
    """Sanitized shape of an intentional error message.

    Merge fields collapse to a placeholder; literal constants (`20%`, thresholds) are kept
    because they are part of the author's intent, not runtime data.
    """
    text = unicodedata.normalize("NFKC", message)
    text = re.sub(r"\{![^}]*\}", MERGE_PLACEHOLDER, text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


# --- projections ------------------------------------------------------------------------


def _flow_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    trigger = facts.get("trigger", {}) or {}
    errors = front.get("intentionalErrors", []) or []
    facets: dict[str, Any] = {
        "flow.processType": facts.get("processType"),
        "flow.status": facts.get("status"),
        "flow.trigger.object": trigger.get("object"),
        "flow.trigger.type": trigger.get("type"),
        "flow.recordTriggerType": trigger.get("recordTriggerType"),
        "flow.hasIntentionalCustomError": bool(errors),
    }
    if errors:
        facets["flow.intentionalError.placement"] = sorted(
            {error.get("presentation", {}).get("mode") for error in errors if error.get("presentation")}
        )
        fields = sorted({e["presentation"].get("field") for e in errors if e.get("presentation", {}).get("field")})
        if fields:
            facets["flow.intentionalError.field"] = fields
        facets["flow.intentionalError.usesLabel"] = any(error.get("customLabelRefs") for error in errors)
    return facets


def _custom_field_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    reference_to = facts.get("referenceTo")
    if isinstance(reference_to, str):
        reference_to = [reference_to]
    return {
        "field.object": facts.get("object"),
        "field.type": facts.get("type"),
        "field.required": facts.get("required"),
        "field.unique": facts.get("unique"),
        "field.externalId": facts.get("externalId"),
        "field.encrypted": facts.get("encrypted"),
        "field.referenceTo": reference_to,
        "field.controllingField": facts.get("controllingField"),
        "field.length": facts.get("length"),
        "field.precision": facts.get("precision"),
        "field.scale": facts.get("scale"),
    }



def _apex_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "apex.kind": facts.get("kind"),
        "apex.sharing": facts.get("sharing"),
        "apex.isTest": facts.get("isTest"),
        "apex.apiVersion": facts.get("apiVersion"),
        "apex.status": facts.get("status"),
        "apex.superclass": facts.get("superclass"),
        "apex.interfaces": facts.get("interfaces"),
        "apex.annotations": facts.get("annotations"),
        "trigger.object": facts.get("triggerObject"),
        "trigger.events": facts.get("triggerEvents"),
    }


def _validation_rule_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "validationRule.object": facts.get("object"),
        "validationRule.active": facts.get("active"),
        "validationRule.errorDisplayField": facts.get("errorDisplayField"),
    }


def _permission_set_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "permissionSet.label": facts.get("label"),
        "permissionSet.license": facts.get("license"),
        "permissionSet.systemPermissions": facts.get("systemPermissions"),
        "permissionSet.objectPermissionCount": facts.get("objectPermissionCount"),
        "permissionSet.fieldPermissionCount": facts.get("fieldPermissionCount"),
        "permissionSet.referencesTruncated": facts.get("referencesTruncated"),
        "permissionSet.truncatedFamilies": facts.get("truncatedFamilies"),
    }



def _custom_object_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "object.kind": facts.get("objectKind"),
        "object.sharingModel": facts.get("sharingModel"),
        "object.deploymentStatus": facts.get("deploymentStatus"),
        "object.eventType": facts.get("eventType"),
        "object.customSettingsType": facts.get("customSettingsType"),
    }


def _record_type_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"recordType.object": facts.get("object"), "recordType.active": facts.get("active")}


def _custom_metadata_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"customMetadata.type": facts.get("type"), "customMetadata.protected": facts.get("protected")}


def _lwc_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"lwc.isExposed": facts.get("isExposed"), "lwc.targets": facts.get("targets")}


def _field_set_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"fieldSet.object": facts.get("object"), "fieldSet.label": facts.get("label")}


def _compact_layout_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"compactLayout.object": facts.get("object"), "compactLayout.label": facts.get("label")}


def _business_process_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "businessProcess.object": facts.get("object"),
        "businessProcess.active": facts.get("isActive"),
        "businessProcess.lifecycleField": facts.get("lifecycleField"),
    }


def _web_link_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "webLink.object": facts.get("object"),
        "webLink.linkType": facts.get("linkType"),
        "webLink.isJavascript": facts.get("isJavascript"),
    }


def _duplicate_rule_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "duplicateRule.object": facts.get("object"),
        "duplicateRule.active": facts.get("active"),
        "duplicateRule.actionOnInsert": facts.get("actionOnInsert"),
        "duplicateRule.actionOnUpdate": facts.get("actionOnUpdate"),
    }


def _matching_rule_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"matchingRule.object": facts.get("object"), "matchingRule.status": facts.get("ruleStatus")}


def _queue_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "queue.name": facts.get("name"),
        "queue.servesObjects": facts.get("servesObjects"),
        "queue.doesSendEmailToMembers": facts.get("doesSendEmailToMembers"),
    }


def _role_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "role.label": facts.get("label"),
        "role.caseAccessLevel": facts.get("caseAccessLevel"),
        "role.opportunityAccessLevel": facts.get("opportunityAccessLevel"),
    }


def _delegate_group_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"delegateGroup.label": facts.get("label"), "delegateGroup.loginAccess": facts.get("loginAccess")}


def _permission_set_group_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "permissionSetGroup.label": facts.get("label"),
        "permissionSetGroup.status": facts.get("status"),
        "permissionSetGroup.permissionSetCount": facts.get("permissionSetCount"),
    }


def _static_resource_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "staticResource.contentType": facts.get("contentType"),
        "staticResource.cacheControl": facts.get("cacheControl"),
    }


def _platform_event_channel_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "platformEventChannel.channelType": facts.get("channelType"),
        "platformEventChannel.label": facts.get("label"),
    }


def _platform_event_channel_member_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "platformEventChannelMember.eventChannel": facts.get("eventChannel"),
        "platformEventChannelMember.selectedEntity": facts.get("selectedEntity"),
    }


def _value_set_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "valueSet.sorted": facts.get("sorted"),
        "valueSet.valueCount": facts.get("valueCount"),
        "valueSet.masterLabel": facts.get("masterLabel"),
    }


def _custom_label_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "customLabel.language": facts.get("language"),
        "customLabel.protected": facts.get("protected"),
        "customLabel.categories": facts.get("categories"),
    }


def _custom_tab_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {"customTab.tabKind": facts.get("tabKind"), "customTab.label": facts.get("label")}


def _custom_application_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "customApplication.navType": facts.get("navType"),
        "customApplication.uiType": facts.get("uiType"),
        "customApplication.hasUtilityBar": facts.get("hasUtilityBar"),
    }


def _flow_definition_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "flowDefinition.active": facts.get("active"),
        "flowDefinition.activeVersionNumber": facts.get("activeVersionNumber"),
    }


def _path_assistant_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "pathAssistant.object": facts.get("object"),
        "pathAssistant.active": facts.get("active"),
        "pathAssistant.recordType": facts.get("recordType"),
    }


def _list_view_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "listView.object": facts.get("object"),
        "listView.queue": facts.get("queue"),
        "listView.filterScope": facts.get("filterScope"),
    }


def _report_type_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "reportType.baseObject": facts.get("baseObject"),
        "reportType.category": facts.get("category"),
        "reportType.deployed": facts.get("deployed"),
    }


def _sharing_rules_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "sharingRules.object": facts.get("object"),
        "sharingRules.criteriaRuleCount": facts.get("criteriaRuleCount"),
        "sharingRules.ownerRuleCount": facts.get("ownerRuleCount"),
    }


def _quick_action_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "quickAction.object": facts.get("object"),
        "quickAction.actionType": facts.get("actionType"),
    }


def _muting_permission_set_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "mutingPermissionSet.label": facts.get("label"),
        "mutingPermissionSet.mutedSystemPermissions": facts.get("mutedSystemPermissions"),
        "mutingPermissionSet.fieldPermissionCount": facts.get("fieldPermissionCount"),
    }


def _dashboard_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "dashboard.folder": facts.get("folder"),
        "dashboard.runningUserPolicy": facts.get("runningUserPolicy"),
    }


def _email_template_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "emailTemplate.folder": facts.get("folder"),
        "emailTemplate.templateType": facts.get("templateType"),
        "emailTemplate.available": facts.get("available"),
    }


def _aura_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "aura.extends": facts.get("extends"),
        "aura.implements": facts.get("implements"),
    }


def _integration_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "integration.endpointHost": facts.get("endpointHost"),
        "integration.label": facts.get("label"),
        "integration.isActive": facts.get("isActive"),
    }


def _profile_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "profile.label": facts.get("label"),
        "profile.custom": facts.get("custom"),
        "profile.userLicense": facts.get("userLicense"),
    }


def _layout_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "layout.object": facts.get("object"),
        "layout.fieldCount": facts.get("fieldCount"),
    }


def _flexipage_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "flexiPage.pageType": facts.get("pageType"),
        "flexiPage.object": facts.get("object"),
        "flexiPage.template": facts.get("template"),
    }


def _workflow_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "workflow.object": facts.get("object"),
        "workflow.ruleCount": facts.get("ruleCount"),
        "workflow.activeRuleCount": facts.get("activeRuleCount"),
    }


def _routing_rules_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "routingRules.object": facts.get("object"),
        "routingRules.ruleCount": facts.get("ruleCount"),
    }


def _approval_process_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "approvalProcess.object": facts.get("object"),
        "approvalProcess.active": facts.get("active"),
        "approvalProcess.stepCount": facts.get("stepCount"),
    }


def _report_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "report.reportType": facts.get("reportType"),
        "report.folder": facts.get("folder"),
        "report.format": facts.get("format"),
    }


def _visualforce_facets(front: dict[str, Any]) -> dict[str, Any]:
    facts = front.get("typeFacts", {})
    return {
        "visualforce.standardController": facts.get("standardController"),
        "visualforce.controller": facts.get("controller"),
        "visualforce.apiVersion": facts.get("apiVersion"),
    }


PROFILE_PROJECTORS = {
    "Flow": _flow_facets,
    "CustomField": _custom_field_facets,
    "ApexClass": _apex_facets,
    "ApexTrigger": _apex_facets,
    "ValidationRule": _validation_rule_facets,
    "PermissionSet": _permission_set_facets,
    "CustomObject": _custom_object_facets,
    "RecordType": _record_type_facets,
    "CustomMetadata": _custom_metadata_facets,
    "LightningComponentBundle": _lwc_facets,
    "FieldSet": _field_set_facets,
    "CompactLayout": _compact_layout_facets,
    "BusinessProcess": _business_process_facets,
    "WebLink": _web_link_facets,
    "DuplicateRule": _duplicate_rule_facets,
    "MatchingRule": _matching_rule_facets,
    "Queue": _queue_facets,
    "Role": _role_facets,
    "DelegateGroup": _delegate_group_facets,
    "PermissionSetGroup": _permission_set_group_facets,
    "StaticResource": _static_resource_facets,
    "PlatformEventChannel": _platform_event_channel_facets,
    "PlatformEventChannelMember": _platform_event_channel_member_facets,
    "GlobalValueSet": _value_set_facets,
    "StandardValueSet": _value_set_facets,
    "CustomLabel": _custom_label_facets,
    "CustomTab": _custom_tab_facets,
    "CustomApplication": _custom_application_facets,
    "FlowDefinition": _flow_definition_facets,
    "PathAssistant": _path_assistant_facets,
    "ListView": _list_view_facets,
    "ReportType": _report_type_facets,
    "SharingRules": _sharing_rules_facets,
    "QuickAction": _quick_action_facets,
    "MutingPermissionSet": _muting_permission_set_facets,
    "Dashboard": _dashboard_facets,
    "EmailTemplate": _email_template_facets,
    "AuraDefinitionBundle": _aura_facets,
    # The nine integration types share the salesforce.integration profile and projector.
    "NamedCredential": _integration_facets,
    "ExternalCredential": _integration_facets,
    "RemoteSiteSetting": _integration_facets,
    "ExternalDataSource": _integration_facets,
    "ExternalServiceRegistration": _integration_facets,
    "ConnectedApp": _integration_facets,
    "AuthProvider": _integration_facets,
    "CspTrustedSite": _integration_facets,
    "CorsWhitelistOrigin": _integration_facets,
    "Profile": _profile_facets,
    "Layout": _layout_facets,
    "FlexiPage": _flexipage_facets,
    "Workflow": _workflow_facets,
    # The three routing-rule containers share the salesforce.routing-rules profile
    # and projector.
    "AssignmentRules": _routing_rules_facets,
    "AutoResponseRules": _routing_rules_facets,
    "EscalationRules": _routing_rules_facets,
    "ApprovalProcess": _approval_process_facets,
    "Report": _report_facets,
    # ApexPage and ApexComponent share the salesforce.visualforce profile and projector.
    "ApexPage": _visualforce_facets,
    "ApexComponent": _visualforce_facets,
}


def project_entry(path: Path, lane: dict[str, Any]) -> dict[str, Any]:
    """Compact, index-ready projection of one canonical entry. Never the authority."""
    front, body = store.split_entry(path.read_text(encoding="utf-8"))
    subject = front["subject"]
    identity = lane["identity"]
    facts = front.get("typeFacts", {})
    purpose = "\n".join(
        line for line in body.splitlines() if line.strip() and not line.startswith("## ")
    )
    facets: dict[str, Any] = {
        "metadataType": subject["metadataType"],
        "fullName": subject["fullName"],
        "namespace": subject.get("namespace"),
        "packageVersionId": front["scope"].get("packageVersionId"),
        "sourceApiVersion": front["scope"].get("sourceApiVersion"),
        "sourcePath": front["source"]["fragments"][0]["path"],
        "profile.id": front["profile"]["id"],
        "profile.version": front["profile"]["version"],
        "effectiveState": lane["lane"],
        "extractionCoverage.typeFacts": front.get("extractionCoverage", {}).get("typeFacts"),
    }
    # `.get`, never `[]`: an entry whose type has no family (hand-authored, unknown type)
    # is already lane not-effective — projection must not crash the index build on it.
    # Owner decision O-2 (2026-08-06): family is a hard facet only, never BM25 text —
    # navigation, not semantics.
    family = store.FAMILY_BY_TYPE.get(subject["metadataType"])
    if family:
        facets["family"] = family
    projector = PROFILE_PROJECTORS.get(subject["metadataType"])
    if projector:
        facets.update({k: v for k, v in projector(front).items() if v is not None})

    edges = []
    for reference in facts.get("references", []) or []:
        edges.append(
            {
                "kind": reference["kind"],
                "target": reference["target"],
                "assurance": reference.get("assurance", "source-derived-heuristic"),
            }
        )

    errors = []
    for error in front.get("intentionalErrors", []) or []:
        message = error.get("messageTemplate", "")
        errors.append(
            {
                "elementApiName": error.get("elementApiName"),
                "elementLabel": error.get("elementLabel"),
                "messageTemplate": message,
                "resolvedDefaultText": error.get("resolvedDefaultText"),
                "fingerprint": message_fingerprint(message),
                "resolvedFingerprint": (
                    message_fingerprint(error["resolvedDefaultText"])
                    if error.get("resolvedDefaultText")
                    else None
                ),
                "presentation": error.get("presentation", {}),
                "reachability": error.get("reachability", {}),
                "limitations": error.get("limitations", []),
            }
        )

    fields: dict[str, list[str]] = {
        "identity": analyze(identity) + analyze(subject["fullName"]),
        "label": analyze(str(facts.get("label") or "")),
        "keyword": [token for kw in front.get("keywords", []) for token in analyze(kw)],
        "purpose": analyze(purpose),
        "attribute": [
            token
            for key, value in facets.items()
            if isinstance(value, str) and key not in {"sourcePath", "effectiveState"}
            for token in analyze(value)
        ],
        "relationTarget": [token for edge in edges for token in analyze(edge["target"])],
        "sourcePath": analyze(facets["sourcePath"]),
        "intentionalError": [
            token
            for error in errors
            for token in analyze(error["messageTemplate"] or "")
            + analyze(error.get("resolvedDefaultText") or "")
            + analyze(error.get("elementApiName") or "")
        ],
    }
    # Org-usage metadata ONLY (contract §14.3): the freshness verdict is recomputed at query
    # time by every consumer, and probe values are structurally excluded from BM25 text and
    # facets — an org number must never be findable, only disclosed beside a verified entry.
    org_usage_meta = []
    org_section = front.get("orgUsage")
    if isinstance(org_section, dict):
        for org_key, block in sorted((org_section.get("orgs") or {}).items()):
            row = {
                "orgKey": org_key,
                "environment": block.get("environment"),
                "observedAt": block.get("observedAt"),
                "expiresAt": block.get("expiresAt"),
            }
            if "fullCopy" in block:
                row["fullCopy"] = block["fullCopy"]
            org_usage_meta.append(row)

    return {
        "identity": identity,
        "path": lane["path"],
        "lane": lane["lane"],
        "orgUsage": org_usage_meta,
        "assurance": front.get("assurance", {}),
        "coverage": front.get("extractionCoverage", {}),
        "limitations": front.get("limitations", []),
        "candidateKeywords": front.get("candidateKeywords", []),
        "purpose": purpose,
        "facets": facets,
        "edges": edges,
        "intentionalErrors": errors,
        "fields": fields,
        # The entry's own account of what it was approved against, carried so `verify_anchor`
        # can re-check it without re-parsing the entry file. It is trustworthy exactly when
        # hydration passes — that proves the file is byte-identical to this projection's source —
        # which is why the check downstream runs only after hydration succeeds.
        "sources": [
            {"path": fragment["path"], "digest": fragment["sourceDigest"]}
            for fragment in front["source"]["fragments"]
        ],
        "citation": {
            "path": lane["path"],
            "entryDigest": lane.get("reviewedContentDigest"),
            # Digest of the WHOLE file. reviewedContentDigest covers identity, profile major,
            # facts, semantics and sensitivity — not source.fragments, scope or keywords, so an
            # edit confined to those passed hydration unseen. This is both stronger and cheaper
            # than the parse-and-recompute it replaces.
            "fileDigest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            "factsDigest": lane.get("factsDigest"),
            "sourceDigest": lane.get("sourceTreeDigest"),
            "profileDigest": front["profile"]["digest"],
        },
    }


# --- index build --------------------------------------------------------------------------


_CODE_FINGERPRINT: str | None = None


def code_fingerprint() -> str:
    """Digest of the code that produces projections and lanes.

    Reuse and freshness were keyed on the data alone. Editing the lane logic therefore left
    the previous generation entirely reusable — no entry file had moved, so every projection
    was reused — and queries went on serving fields the current code would never produce.
    Observed: draft entries kept the null citation digest written before the fix, so hydration
    dropped every relation hit as "entry changed since the index was built" while the entries
    were in fact untouched. A stat stamp cannot see a code change, so the code is part of the
    key: edit the projector and the previous generation is discarded automatically.

    relation_kinds is in the tuple even though nothing here derives assurance from it: the
    vocabulary decides what an entry ASSERTS, so moving a kind into HEURISTIC_REF_KINDS changes
    stored edges. Without it in the key, that edit would change no fingerprinted byte and every
    cached projection would be reused as fresh — serving the old `source-exact` marker."""

    global _CODE_FINGERPRINT
    if _CODE_FINGERPRINT is None:
        parts = []
        for module in (sys.modules[__name__], store, relation_kinds, sys.modules[analyze.__module__]):
            path = Path(getattr(module, "__file__", "") or "")
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"
            parts.append((path.name, digest))
        _CODE_FINGERPRINT = store.canonical_digest(sorted(parts))
    return _CODE_FINGERPRINT


def corpus_fingerprint() -> str:
    """Coarse freshness signal: entry count, newest stamp, ledger stamp, analyzer, code.

    Recomputing the full projection per query re-parsed the whole corpus (~1s at 200 entries),
    so this replaced it with a per-file stat sweep — which was still linear: 11.6 µs per entry
    measured, i.e. ~174 ms of pure staleness-checking on every CLI call at 15k entries, before
    any query work, and materially worse on the team's NTFS + Defender path.

    Aggregating to (count, newest stamp, total bytes) keeps the same guarantee at a fraction of
    the cost. Hydration is NOT the argument for weakening this signal further: it re-reads and
    digest-checks every row a query SERVES, so it catches a tampered served entry — but an
    in-place edit that changes keywords or scope makes an entry stop ranking, and a row that is
    never served is a row hydration never sees. A missed staleness signal here is therefore a
    silent false negative, which is why the per-file stat stays and only its arithmetic changed.

    The per-entry mtime is the expensive part and it is already at its floor: `DirEntry.stat()`
    is one `fstatat` on POSIX, and on Windows the value comes free with the directory read.
    Dropping to directory mtimes alone measured 0.53 µs/entry against 2.5 (macOS/APFS, 3000
    entries) — five times cheaper, and it cannot see a content edit written in place rather than
    renamed over, so it was rejected.
    """
    # os.scandir, not rglob+stat: the directory read already carries the metadata, so this is
    # one syscall per file instead of two. Measured 11.6 -> 3.4 µs per entry.
    newest = 0
    count = 0
    # Folded separately, not into the max(). `max(newest, st_mtime_ns, st_size)` could only ever
    # be won by a file larger than 1.7e18 bytes, so the size term was dead and the signal was
    # (count, newest) alone. As a running total it does real work: two edits that cancel out in
    # both count and newest mtime — the one case the docstring admits this signal cannot see —
    # are now caught whenever they change a byte count.
    total_bytes = 0
    stack = [str(store.ARTIFACTS_ROOT)] if store.ARTIFACTS_ROOT.is_dir() else []
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                # Name first, then is_dir: entry paths put `.md` only on leaf files (the type
                # and namespace segments come from the identity grammar and cannot contain a
                # dot), so a `.md` name is a file by construction and the d_type check on it is
                # work nobody needs. Measured ~4% of the sweep.
                if entry.name.endswith(".md"):
                    stat = entry.stat(follow_symlinks=False)
                    count += 1
                    total_bytes += stat.st_size
                    if stat.st_mtime_ns > newest:
                        newest = stat.st_mtime_ns
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
    ledger = store.LEDGER_PATH
    ledger_stat = (ledger.stat().st_size, ledger.stat().st_mtime_ns) if ledger.is_file() else (0, 0)
    return store.canonical_digest(
        {
            "entries": [count, newest, total_bytes],
            "ledger": ledger_stat,
            "analyzer": ANALYZER_VERSION,
            "code": code_fingerprint(),
        }
    )


def fold_target(target: str) -> str:
    """Posting key for an edge target. Folded like facet keys are folded on write."""
    return unicodedata.normalize("NFKC", target).casefold()


LOCAL_NAME_SUFFIXES = ("__c", "__e", "__mdt", "__b", "__x")


def _local_custom_name(name: str) -> bool:
    """entry_edge_health's published rule: force-app is the only place this name can come from.

    `ns__Thing__c` belongs to an installed package — it is not in this repo and never will be."""

    for suffix in LOCAL_NAME_SUFFIXES:
        if name.endswith(suffix):
            return "__" not in name[: -len(suffix)]
    return False


def target_decidable(target: str) -> bool:
    """Whether this index could ever hold an entry for the target.

    Mirrors `force_app_knowledge._decidable_targets`: only an unnamespaced __c/__e/__mdt/__b/__x
    name is decidable. A dotted target needs BOTH halves package-local — `Category__c.Id` will
    never have a CustomField entry, so its `no-entry` proves nothing."""

    object_name, _, member = target.partition(".")
    if not member:
        return _local_custom_name(target)
    return _local_custom_name(object_name) and _local_custom_name(member)


def build_relation_index(projections: list[dict[str, Any]]) -> dict[str, Any]:
    """Who points at each target, and what that target resolves to.

    The old posting was `target -> [identity]`: it answered "does anything reference this" and
    nothing else. The kind and the assurance — the two things that decide whether an edge may be
    shown by default and what it means — had to be recovered by re-reading every source document,
    which is why `explain` and `impact` scanned the whole corpus.

    Resolution is computed here, once, rather than stored in entries: an entry may not assert
    that its target exists, because that depends on another artifact. An unresolvable target is
    kept and labelled, never dropped — "this points somewhere I have no entry for" is a finding,
    and silently discarding it would make a partial graph look complete.
    """

    by_full_name: dict[str, list[str]] = defaultdict(list)
    # Extractors emit the token source wrote — `object-token` on `a.Status__c` yields the bare
    # `Status__c` — while a field entry's fullName is the qualified `Object.Field`. Without this
    # index a fifth of the probe corpus's `no-entry` edges named fields that had approved
    # entries, and `impact --direction outgoing` dead-ended one hop early on all of them.
    by_member: dict[str, list[str]] = defaultdict(list)
    identities = set()
    for item in projections:
        identities.add(item["identity"])
        full_name = item["facets"].get("fullName")
        if full_name:
            by_full_name[fold_target(str(full_name))].append(item["identity"])
            owner, _, member = str(full_name).rpartition(".")
            if owner:
                by_member[fold_target(member)].append(item["identity"])

    by_target: dict[str, dict[str, Any]] = {}
    for item in projections:
        for edge in item["edges"]:
            key = fold_target(edge["target"])
            row = by_target.setdefault(
                key, {"spellings": set(), "incoming": [], "targetIdentity": None, "resolution": "no-entry"}
            )
            row["spellings"].add(edge["target"])
            row["incoming"].append([item["identity"], edge["kind"], edge["assurance"]])

    for key, row in by_target.items():
        candidates = by_full_name.get(key, [])
        if not candidates and key in {fold_target(name) for name in identities}:
            candidates = [name for name in identities if fold_target(name) == key]
        if len(candidates) == 1:
            row["targetIdentity"] = candidates[0]
            row["resolution"] = "resolved"
        elif len(candidates) > 1:
            # Namespace twins. Guessing one would silently pick a package's artifact over the
            # subscriber's; the caller is told instead.
            row["resolution"] = "ambiguous"
            row["candidates"] = sorted(candidates)
        else:
            members = by_member.get(key, [])
            if len(members) == 1:
                row["targetIdentity"] = members[0]
                # A distinct value, not "resolved": the qualified/bare distinction stays
                # visible to anyone auditing how an edge was settled.
                row["resolution"] = "resolved-by-member"
            elif len(members) > 1:
                row["resolution"] = "ambiguous"
                row["candidates"] = sorted(members)
        row["decidable"] = target_decidable(sorted(row["spellings"])[0])
        row["spellings"] = sorted(row["spellings"])
        row["incoming"] = sorted(row["incoming"])

    # Sources whose own edge list was capped by the collector. The entry records this locally
    # (typeFacts.referencesTruncated / truncatedFamilies) but nothing read it at query time, so
    # "which permission sets grant edit on this field?" returned a complete-looking list that
    # systematically omitted every PermissionSet with more than ~300 grants — and the collector
    # discards fieldPermissions FIRST, so the security question failed closed the wrong way.
    truncated: dict[str, list[str]] = {}
    for item in projections:
        families = item["facets"].get("permissionSet.truncatedFamilies")
        if item["facets"].get("permissionSet.referencesTruncated"):
            for family in (families or ["unspecified"]):
                truncated.setdefault(str(family), []).append(item["identity"])

    return {
        "byTarget": by_target,
        "byFullName": {name: sorted(ids) for name, ids in by_full_name.items()},
        "truncatedSources": {family: sorted(ids) for family, ids in truncated.items()},
    }


def entry_set_digest(projections: list[dict[str, Any]]) -> str:
    payload = sorted(
        (item["identity"], item["path"], item["lane"], item["citation"]["entryDigest"] or "")
        for item in projections
    )
    return store.canonical_digest(
        {
            "entries": payload,
            "analyzer": ANALYZER_VERSION,
            "schema": INDEX_SCHEMA_VERSION,
            "policy": POLICY_VERSION,
            "code": code_fingerprint(),
        }
    )


def _stamp_of(path: Path) -> list[Any]:
    try:
        stat = path.stat()
    except OSError:
        return [path.name, None, None]
    return [path.name, stat.st_size, stat.st_mtime_ns]


def projection_dependencies(path: Path, fragments: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything a projection's content AND lane depend on.

    The lane is not a function of the entry file alone: source drift moves it to
    approved-drifted and a ledger append can approve or revoke it. Keying reuse on the entry
    file alone silently served a stale lane (caught by the drifted-lane golden query), so the
    key covers the entry, every source fragment, and the ledger."""

    ledger = store.LEDGER_PATH
    return {
        "entry": _stamp_of(path),
        "sources": sorted(_stamp_of(store.ROOT / fragment["path"]) for fragment in fragments),
        "ledger": _stamp_of(ledger) if ledger.is_file() else None,
    }


def load_previous_projections() -> dict[str, dict[str, Any]]:
    """Projections from the current generation, keyed by path+stamp for reuse."""
    root = cache_root()
    pointer = root / "current.json"
    if not pointer.is_file():
        return {}
    try:
        current = json.loads(pointer.read_text(encoding="utf-8"))
        documents_path = root / current.get("directory", "") / "documents.jsonl"
        manifest = json.loads((root / current["directory"] / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return {}
    if manifest.get("analyzerVersion") != ANALYZER_VERSION or manifest.get("schemaVersion") != INDEX_SCHEMA_VERSION:
        return {}  # a projection built by a different analyzer may not be reused
    if manifest.get("codeFingerprint") != code_fingerprint():
        return {}  # projections built by different projector/lane code may not be reused
    reusable: dict[str, dict[str, Any]] = {}
    try:
        for line in documents_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            document = json.loads(line)
            if document.get("_deps"):
                reusable[document["path"]] = document
    except (OSError, ValueError):
        return {}
    return reusable


def collect_projections(reuse: dict[str, dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project every entry, reusing unchanged ones from the previous generation.

    A full projection costs ~5 ms per entry (measured), so rebuilding 15k entries after a
    single approval would take over a minute. Reuse is keyed on the entry's path plus its
    size/mtime stamp and is only ever a cache: anything whose stamp moved is re-projected,
    and a changed analyzer version discards the whole previous generation."""

    reuse = reuse if reuse is not None else {}
    latest = store.ledger_latest(store.read_ledger())
    projections: list[dict[str, Any]] = []
    stats = {"reused": 0, "projected": 0}
    for path in store.all_entry_paths():
        relative = path.relative_to(store.ROOT).as_posix()
        cached = reuse.get(relative)
        if cached is not None:
            fragments = cached.get("_deps", {}).get("sourcePaths") or []
            expected = projection_dependencies(path, [{"path": item} for item in fragments])
            if cached["_deps"].get("stamps") == expected:
                projections.append(cached)
                stats["reused"] += 1
                continue
        lane = store.compute_lane(path, latest)
        document = project_entry(path, lane)
        front, _ = store.split_entry(path.read_text(encoding="utf-8"))
        fragment_paths = [fragment["path"] for fragment in front["source"]["fragments"]]
        document["_deps"] = {
            "sourcePaths": fragment_paths,
            "stamps": projection_dependencies(path, front["source"]["fragments"]),
        }
        projections.append(document)
        stats["projected"] += 1
    return sorted(projections, key=lambda item: item["identity"]), stats


def build_index(check: bool = False, full: bool = False) -> dict[str, Any]:
    projections, stats = collect_projections({} if full else load_previous_projections())
    generation = entry_set_digest(projections)
    root = cache_root()
    pointer = root / "current.json"
    if check:
        if not pointer.is_file():
            raise SearchError("INDEX STALE / REBUILD REQUIRED: no generation pointer")
        current = json.loads(pointer.read_text(encoding="utf-8"))
        if current.get("generation") != generation:
            raise SearchError("INDEX STALE / REBUILD REQUIRED: entry set changed since the last build")
        return {"outcome": "PASS", "generation": generation, "entries": len(projections)}

    generation_dir = root / f"gen-{generation[7:23]}"
    generation_dir.mkdir(parents=True, exist_ok=True)
    documents = generation_dir / "documents.jsonl"
    offsets: dict[str, list[int]] = {}
    lanes: dict[str, list[str]] = defaultdict(list)
    facet_postings: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    token_postings: dict[str, list[str]] = defaultdict(list)
    relation_postings: dict[str, list[str]] = defaultdict(list)
    document_frequency: dict[str, int] = defaultdict(int)
    field_length_totals: dict[str, list[int]] = defaultdict(list)
    position = 0
    with documents.open("w", encoding="utf-8", newline="\n") as handle:
        for item in projections:
            line = json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n"
            encoded = line.encode("utf-8")
            offsets[item["identity"]] = [position, len(encoded)]
            position += len(encoded)
            handle.write(line)
            lanes[item["lane"]].append(item["identity"])
            for key, value in item["facets"].items():
                values = value if isinstance(value, list) else [value]
                for entry in values:
                    if entry is None:
                        continue
                    facet_postings[key][str(entry).casefold()].append(item["identity"])
            for edge in item["edges"]:
                relation_postings[edge["target"]].append(item["identity"])
                relation_postings[fold_target(edge["target"])].append(item["identity"])
            seen_tokens = {token for field in item["fields"].values() for token in field}
            for token in seen_tokens:
                token_postings[token].append(item["identity"])
                document_frequency[token] += 1
            for field, tokens in item["fields"].items():
                field_length_totals[field].append(len(tokens))
    postings = {
        "offsets": offsets,
        "lanes": {lane: sorted(ids) for lane, ids in lanes.items()},
        "facets": {
            key: {value: sorted(ids) for value, ids in values.items()}
            for key, values in facet_postings.items()
        },
        "tokens": {token: sorted(ids) for token, ids in token_postings.items()},
        "relations": {target: sorted(set(ids)) for target, ids in relation_postings.items()},
        "reverse": build_relation_index(projections),
        "documentFrequency": dict(document_frequency),
        "averageFieldLength": {
            field: (sum(lengths) / len(lengths)) if lengths else 1.0
            for field, lengths in field_length_totals.items()
        },
        "documentCount": len(projections),
    }
    for name, payload in (
        ("offsets", postings["offsets"]),
        ("lanes", postings["lanes"]),
        ("facets", postings["facets"]),
        ("relations", postings["relations"]),
        ("reverse", postings["reverse"]),
        ("tokens", postings["tokens"]),
        ("stats", {
            "documentFrequency": postings["documentFrequency"],
            "averageFieldLength": postings["averageFieldLength"],
            "documentCount": postings["documentCount"],
        }),
    ):
        with (generation_dir / f"{name}.json").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    manifest = {
        "kind": "knowledge-search-manifest",
        "schemaVersion": INDEX_SCHEMA_VERSION,
        "analyzerVersion": ANALYZER_VERSION,
        "policyVersion": POLICY_VERSION,
        "generation": generation,
        "entryCount": len(projections),
        "laneCounts": {
            lane: sum(1 for item in projections if item["lane"] == lane) for lane in ALL_LANES
        },
        # Pinned per generation so `build --check` covers them and drift in edge resolution is
        # visible where every other corpus statistic already is.
        "edgeResolution": {
            "targets": len(postings["reverse"]["byTarget"]),
            "resolutionCounts": {
                resolution: sum(
                    1 for row in postings["reverse"]["byTarget"].values()
                    if row["resolution"] == resolution
                )
                for resolution in sorted(
                    {row["resolution"] for row in postings["reverse"]["byTarget"].values()}
                )
            },
            "decidableNoEntry": sum(
                1 for row in postings["reverse"]["byTarget"].values()
                if row["resolution"] == "no-entry" and row["decidable"]
            ),
        },
        "metadataTypeCounts": {
            metadata_type: sum(
                1 for item in projections if item["facets"]["metadataType"] == metadata_type
            )
            for metadata_type in sorted({item["facets"]["metadataType"] for item in projections})
        },
        "familyCounts": {
            family: sum(1 for item in projections if item["facets"].get("family") == family)
            for family in sorted(
                {item["facets"]["family"] for item in projections if "family" in item["facets"]}
            )
        },
        "corpusFingerprint": corpus_fingerprint(),
        "codeFingerprint": code_fingerprint(),
        "documentsDigest": store.canonical_digest(documents.read_text(encoding="utf-8")),
        "complete": True,
    }
    with (generation_dir / "manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temp_pointer = root / "current.json.tmp"
    with temp_pointer.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {"generation": generation, "directory": generation_dir.name}, indent=2, sort_keys=True
            )
            + "\n"
        )
    temp_pointer.replace(pointer)
    for stale in root.glob("gen-*"):
        if stale.is_dir() and stale.name != generation_dir.name:
            shutil.rmtree(stale, ignore_errors=True)
    return {
        "outcome": "BUILT",
        "generation": generation,
        "entries": len(projections),
        "reusedProjections": stats["reused"],
        "rebuiltProjections": stats["projected"],
    }


def load_index() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the current generation, refusing to answer from a stale or partial index."""
    root = cache_root()
    pointer = root / "current.json"
    if not pointer.is_file():
        raise SearchError("INDEX STALE / REBUILD REQUIRED: run `knowledge_search.py build`")
    current = json.loads(pointer.read_text(encoding="utf-8"))
    generation_dir = root / current.get("directory", "")
    manifest_path = generation_dir / "manifest.json"
    documents_path = generation_dir / "documents.jsonl"
    if not manifest_path.is_file() or not documents_path.is_file():
        raise SearchError("INDEX STALE / REBUILD REQUIRED: generation is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("complete") or manifest.get("analyzerVersion") != ANALYZER_VERSION:
        raise SearchError("INDEX STALE / REBUILD REQUIRED: incompatible or partial generation")
    if manifest.get("corpusFingerprint") != corpus_fingerprint():
        raise SearchError("INDEX STALE / REBUILD REQUIRED: entries changed since the last build")
    if not (generation_dir / "offsets.json").is_file():
        raise SearchError("INDEX STALE / REBUILD REQUIRED: generation predates the postings index")
    return DocumentStore(documents_path, generation_dir), manifest


class DocumentStore:
    """Random-access reader over one generation.

    Queries resolve a candidate identity set from the postings first and hydrate only those
    documents by byte offset; parsing every line made query latency linear in corpus size,
    which is what broke the p95 budget past ~5 000 entries (review package §8)."""

    def __init__(self, path: Path, generation_dir: Path):
        self.path = path
        self.generation_dir = generation_dir
        self._cache: dict[str, dict[str, Any]] = {}
        self._postings: dict[str, Any] = {}
        self.document_reads = 0
        self.posting_bytes = 0

    def posting_file(self, name: str) -> dict[str, Any]:
        """Load one posting file on first use.

        Token postings dominate the index by volume but are only needed for lexical queries;
        loading them for an identity or facet lookup was pure latency."""
        if name not in self._postings:
            path = self.generation_dir / f"{name}.json"
            self._postings[name] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            # Counted so a query can report how much index it touched. documentReads alone is
            # blind to this: a regression that loaded every posting family per query — token
            # postings reach ~15 MB at 15k entries — would not move that counter at all.
            self.posting_bytes += path.stat().st_size if path.is_file() else 0
        return self._postings[name]

    @property
    def postings(self) -> dict[str, Any]:
        # Compatibility surface for callers that read a specific family.
        return {
            "offsets": self.posting_file("offsets"),
            "facets": self.posting_file("facets"),
            "documentFrequency": self.posting_file("stats").get("documentFrequency", {}),
            "averageFieldLength": self.posting_file("stats").get("averageFieldLength", {}),
        }

    @property
    def count(self) -> int:
        return int(self.posting_file("stats").get("documentCount", 0))

    def identities(self) -> list[str]:
        return sorted(self.posting_file("offsets"))

    def get(self, identity: str) -> dict[str, Any] | None:
        if identity in self._cache:
            return self._cache[identity]
        location = self.posting_file("offsets").get(identity)
        if location is None:
            return None
        offset, length = location
        with self.path.open("rb") as handle:
            handle.seek(offset)
            document = json.loads(handle.read(length).decode("utf-8"))
        self.document_reads += 1
        self._cache[identity] = document
        return document

    def load_many(self, identities: Iterable[str]) -> list[dict[str, Any]]:
        return [document for document in (self.get(identity) for identity in identities) if document]

    def lane_ids(self, lanes: Iterable[str]) -> set[str]:
        result: set[str] = set()
        for lane in lanes:
            result.update(self.posting_file("lanes").get(lane, []))
        return result

    def facet_ids(self, key: str, value: str) -> set[str] | None:
        """Identity set for an exact facet value; None when the operator needs full evaluation."""
        values = self.posting_file("facets").get(key)
        if values is None:
            return set()
        return set(values.get(value.casefold(), []))

    def token_ids(self, token: str) -> set[str]:
        return set(self.posting_file("tokens").get(token, []))

    def relation_ids(self, target: str) -> set[str]:
        return set(self.posting_file("relations").get(target, []))

    def target_row(self, target: str) -> dict[str, Any]:
        """Everything the index knows about one edge target: who points at it, what it is."""
        reverse = self.posting_file("reverse").get("byTarget", {})
        return reverse.get(fold_target(target), {
            "spellings": [], "incoming": [], "targetIdentity": None, "resolution": "no-target"
        })

    def incoming_edges(
        self, target: str, *, kinds: set[str] | None = None, include_heuristic: bool = False
    ) -> list[dict[str, Any]]:
        """Every edge pointing at `target`, one row per edge.

        One row per EDGE, not per source: an entry that both queries and writes the same object
        is two facts about it, and collapsing them to one hid half the answer."""

        rows = []
        for source, kind, assurance in self.target_row(target)["incoming"]:
            if kinds is not None and kind not in kinds:
                continue
            if not include_heuristic and assurance != relation_kinds.SOURCE_EXACT:
                continue
            rows.append({"source": source, "kind": kind, "assurance": assurance})
        return rows

    def identities_for_full_name(self, full_name: str) -> list[str]:
        return list(self.posting_file("reverse").get("byFullName", {}).get(fold_target(full_name), []))


# --- query ----------------------------------------------------------------------------------


def facet_value(document: dict[str, Any], key: str) -> Any:
    return document["facets"].get(key)


def facet_matches(document: dict[str, Any], key: str, operator: str, value: str) -> bool:
    actual = facet_value(document, key)
    if operator == "exists":
        return actual is not None
    if actual is None:
        return False
    if isinstance(actual, bool):
        return operator == "eq" and str(actual).casefold() == value.casefold()
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        try:
            number = float(value)
        except ValueError:
            raise SearchError(f"facet {key} expects a number, got {value!r}")
        return {"eq": actual == number, "gte": actual >= number, "lte": actual <= number}.get(
            operator, False
        )
    if isinstance(actual, list):
        casefolded = [str(item).casefold() for item in actual]
        if operator in {"has", "eq"}:
            return value.casefold() in casefolded
        if operator == "in":
            return bool(set(casefolded) & {part.casefold() for part in value.split("|")})
        if operator == "prefix":
            return any(item.startswith(value.casefold()) for item in casefolded)
        return False
    text = str(actual).casefold()
    if operator == "eq":
        return text == value.casefold()
    if operator == "in":
        return text in {part.casefold() for part in value.split("|")}
    if operator == "prefix":
        return text.startswith(value.casefold())
    if operator == "has":
        return value.casefold() in text
    raise SearchError(f"operator {operator!r} is not valid for facet {key}")


def parse_facet(expression: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_.]*)(?::([a-z]+))?=(.*)", expression)
    if not match:
        raise SearchError(f"--facet must be key[:op]=value, got {expression!r}")
    key, operator, value = match.group(1), match.group(2) or "eq", match.group(3)
    if operator not in FACET_OPERATORS:
        raise SearchError(f"unknown operator {operator!r}; valid: {', '.join(FACET_OPERATORS)}")
    known = set(GLOBAL_FACETS) | {facet for facets in PROFILE_FACETS.values() for facet in facets}
    if key not in known:
        raise SearchError(f"unknown facet {key!r}; run `capabilities` for the valid set")
    return key, operator, value


def query_term_stats(store_index: "DocumentStore", query_tokens: list[str]) -> list[dict[str, Any]]:
    """Corpus-derived honesty about each query token, before any scoring happens.

    BM25's idf discounts a saturated term but never zeroes it, so a sentence-shaped query
    whose only content word matches nothing still accumulates score from its function words —
    and the verdict reads OK. The statistics the index already persists at build time are
    enough to name which tokens could possibly discriminate."""

    statistics = store_index.posting_file("stats")
    document_frequency = statistics.get("documentFrequency", {})
    corpus = max(store_index.count, 1)
    rows = []
    for token in sorted(set(query_tokens)):
        frequency = document_frequency.get(token, 0)
        rows.append({
            "term": token,
            "documentFrequency": frequency,
            "corpusSize": corpus,
            "idf": round(math.log(1 + (corpus - frequency + 0.5) / (frequency + 0.5)), 4),
            "matched": frequency > 0,
            "saturated": corpus >= DF_SATURATION_MIN_CORPUS and frequency >= DF_SATURATION * corpus,
        })
    return rows


def bm25f(store_index: "DocumentStore", candidates: list[dict[str, Any]], query_tokens: list[str]) -> dict[str, tuple[float, list[dict[str, Any]]]]:
    """Rank candidates with corpus statistics precomputed at build time.

    Document frequencies and average field lengths come from the postings index, so ranking
    no longer has to read the whole corpus on every query."""

    if not query_tokens:
        return {}
    statistics = store_index.posting_file("stats")
    document_frequency = statistics.get("documentFrequency", {})
    average_length = statistics.get("averageFieldLength", {})
    total = max(store_index.count, 1)
    scored: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    for document in candidates:
        score = 0.0
        matched: list[dict[str, Any]] = []
        for token in set(query_tokens):
            frequency = document_frequency.get(token, 0)
            idf = math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            weighted_tf = 0.0
            for field, tokens in document["fields"].items():
                count = tokens.count(token)
                if not count:
                    continue
                length = len(tokens) or 1
                norm = 1 - BM25_B + BM25_B * (length / (average_length.get(field) or 1.0))
                weighted_tf += FIELD_WEIGHTS.get(field, 1.0) * count / norm
                matched.append({"field": field, "match": "lexical", "value": token})
            if weighted_tf:
                score += idf * (weighted_tf * (BM25_K1 + 1)) / (weighted_tf + BM25_K1)
        if score:
            scored[document["identity"]] = (score, matched)
    return scored


SNIPPET_WINDOW = 240
SNIPPET_BASIS = (
    "excerpt of the entry's Purpose prose, clipped for display; the citable unit is "
    "citation.path + citation.entryDigest, never this string"
)


def purpose_snippet(document: dict[str, Any], matched: list[dict[str, Any]]) -> str | None:
    """A windowed excerpt of the Purpose prose, so a ranking error costs a glance instead of a
    file open. Centred on the longest matched purpose term when one is findable in the raw
    prose (analyzer tokens are normalised, so a deaccented match may not be), else the head of
    the text. An unfilled draft sentinel is an absence, not prose — `--state draft` routes
    drafts through this same funnel. Apart from the ellipsis marks the return value is a
    substring of the hydration-verified entry file, which is what makes serving it safe."""

    text = (document.get("purpose") or "").strip()
    if not text or text.startswith("<AGENT_"):
        return None
    if len(text) <= SNIPPET_WINDOW:
        return text
    lowered = text.lower()
    best: tuple[int, int] | None = None  # (term length, position in text)
    for row in matched:
        if row.get("field") != "purpose":
            continue
        term = str(row.get("value") or "")
        position = lowered.find(term.lower())
        if position >= 0 and (best is None or len(term) > best[0]):
            best = (len(term), position)
    if best is None:
        start, end = 0, SNIPPET_WINDOW
    else:
        centre = best[1] + best[0] // 2
        start = max(0, centre - SNIPPET_WINDOW // 2)
        end = min(len(text), start + SNIPPET_WINDOW)
        start = max(0, end - SNIPPET_WINDOW)
    if start > 0:
        boundary = text.find(" ", start)
        if 0 <= boundary < end:
            start = boundary + 1
    if end < len(text):
        boundary = text.rfind(" ", start, end)
        if boundary > start:
            end = boundary
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def hit_of(document: dict[str, Any], score: float, matched: list[dict[str, Any]], match_class: str) -> dict[str, Any]:
    return {
        "artifactId": document["identity"],
        "metadataType": document["facets"]["metadataType"],
        "fullName": document["facets"]["fullName"],
        "matchClass": match_class,
        "score": round(score, 4),
        "scoreComparableWithinQueryOnly": True,
        "matchedOn": matched[:8],
        "snippet": purpose_snippet(document, matched),
        "snippetBasis": SNIPPET_BASIS,
        "lifecycle": document["lane"],
        "assurance": document["assurance"],
        "scope": {
            "namespace": document["facets"]["namespace"],
            "packageVersionId": document["facets"]["packageVersionId"],
            "sourceApiVersion": document["facets"]["sourceApiVersion"],
        },
        "coverage": document["coverage"],
        "limitations": document["limitations"],
        "citation": document["citation"],
    }


def hydrate(hits: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Re-read and digest-check the canonical entries behind the results we are about to serve.

    Contract §25.6: compact search first, then load and verify the selected entries. This is
    what makes the cheap freshness fingerprint safe — a file that changed without changing its
    stat signature still cannot be served, because its recomputed lane and digest are checked
    here before the hit leaves the process."""

    verified: list[dict[str, Any]] = []
    gaps: list[str] = []
    for hit in hits:
        path = store.ROOT / hit["citation"]["path"]
        if not path.is_file():
            gaps.append(f"{hit['artifactId']}: entry file disappeared since the index was built")
            continue
        # The ledger is already covered by the freshness fingerprint (a ledger append or
        # revocation invalidates the whole generation), so hydration only has to prove the
        # FILE still holds the content the projection was built from — which is exactly the
        # case a stat-based fingerprint could theoretically miss. Re-reading the 15k-line
        # ledger per query was pure overhead.
        expected_file = hit["citation"].get("fileDigest")
        actual_file = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_file and actual_file != expected_file:
            # Whole-file comparison: catches every byte, including the frontmatter fields
            # reviewedContentDigest does not cover. One hash instead of a parse plus three
            # digest computations.
            gaps.append(
                f"{hit['artifactId']}: entry changed since the index was built — rebuild the index"
            )
            continue
        try:
            frontmatter, body = store.split_entry(path.read_text(encoding="utf-8"))
            recomputed = store.reviewed_content_digest(frontmatter, body)
        except store.StoreError as error:
            gaps.append(f"{hit['artifactId']}: entry no longer parses ({error})")
            continue
        subject = frontmatter["subject"]
        identity = store.identity_of(
            subject["metadataType"], subject.get("namespace"), subject["fullName"]
        )
        if identity != hit["artifactId"] or recomputed != hit["citation"]["entryDigest"]:
            gaps.append(
                f"{hit['artifactId']}: entry changed since the index was built — rebuild the index"
            )
            continue
        verified.append(hit)
    return verified, gaps


def run_search(args: argparse.Namespace) -> dict[str, Any]:
    documents, manifest = load_index()
    states = list(args.state or ESTABLISHED_STATES)
    facets = [parse_facet(expression) for expression in (args.facet or [])]
    excluded = defaultdict(int)
    interpreted: dict[str, Any] = {
        "mode": args.mode,
        "text": args.text,
        "identity": args.identity,
        "states": states,
        "metadataType": args.metadata_type,
        "namespace": args.namespace,
        "facets": [f"{key}:{operator}={value}" for key, operator, value in facets],
        "relation": (
            {"anchor": args.relation_anchor, "kind": args.relation_kind, "direction": args.direction}
            if args.relation_anchor
            else None
        ),
        "top": args.top,
    }
    # Computed here, NOT inside the candidate-seeding block below: seeding is guarded by
    # `and not other_facets`, and the honesty of queryTerms must not depend on which filters
    # the caller happened to add.
    query_terms = query_term_stats(documents, analyze(args.text)) if args.text else []

    # Hard filters resolve to identity sets through the postings index; only the survivors
    # are hydrated. Exact-equality facets narrow via postings, other operators are evaluated
    # on the (already narrowed) candidate documents.
    all_ids = set(documents.identities())
    candidate_ids = documents.lane_ids(states)
    excluded["lifecycle"] = len(all_ids) - len(candidate_ids)
    if args.metadata_type:
        by_type = documents.facet_ids("metadataType", args.metadata_type)
        excluded["metadataType"] = len(candidate_ids - by_type)
        candidate_ids &= by_type
    if args.namespace is not None:
        wanted = "c" if args.namespace == "c" else args.namespace
        by_namespace = (
            documents.facet_ids("namespace", wanted)
            if args.namespace != "c"
            else candidate_ids - set().union(*(
                set(values) for values in documents.posting_file("facets").get("namespace", {}).values()
            ) or [set()])
        )
        excluded["scope"] = len(candidate_ids - by_namespace)
        candidate_ids &= by_namespace
    exact_facets = [item for item in facets if item[1] == "eq"]
    other_facets = [item for item in facets if item[1] != "eq"]
    for key, _operator, value in exact_facets:
        by_facet = documents.facet_ids(key, value)
        excluded["facet"] += len(candidate_ids - by_facet)
        candidate_ids &= by_facet
    lexical_truncated = 0
    # Hoisted: whether the query matched ANYTHING lexically is the difference between "no such
    # thing" and "matched, then filtered out by your lane". Reporting the second as the first is
    # how `search --text mpsaCard` came back "No lexical match" for an entry sitting in the index.
    lexical_token_ids: set[str] = set()
    if args.text and not other_facets:
        # Seed candidates from the RAREST query token and intersect outwards. A common term
        # ("queue") matches the whole corpus, so a naive union would hydrate everything and
        # put latency back where the postings index was meant to remove it.
        frequency = documents.posting_file("stats").get("documentFrequency", {})
        tokens_by_rarity = sorted(set(analyze(args.text)), key=lambda token: frequency.get(token, 0))
        token_ids: set[str] = set()
        for token in tokens_by_rarity:
            posting = documents.token_ids(token)
            if not posting:
                continue
            token_ids = posting if not token_ids else (token_ids | posting)
            if len(token_ids) >= LEXICAL_CANDIDATE_CAP:
                break
        lexical_token_ids = token_ids
        candidate_ids &= token_ids
        if len(candidate_ids) > LEXICAL_CANDIDATE_CAP:
            # Never silently truncate: the cap is reported alongside the results.
            rarest = documents.token_ids(tokens_by_rarity[0]) & candidate_ids
            lexical_truncated = len(candidate_ids) - len(rarest if rarest else candidate_ids)
            if rarest:
                candidate_ids = rarest
            else:
                candidate_ids = set(sorted(candidate_ids)[:LEXICAL_CANDIDATE_CAP])
    needs_full_scan = bool(args.text) or bool(other_facets) or args.mode == "intentional-flow-error" or (
        not args.identity and not args.relation_anchor
    )
    candidates = documents.load_many(sorted(candidate_ids)) if needs_full_scan else []
    if other_facets:
        kept = []
        for document in candidates:
            if all(facet_matches(document, key, operator, value) for key, operator, value in other_facets):
                kept.append(document)
            else:
                excluded["facet"] += 1
        candidates = kept

    gaps: list[str] = []
    results: list[dict[str, Any]] = []
    match_class = "structured"

    if args.mode == "intentional-flow-error":
        # FlowCustomError-only lookup: exact source text, then resolved label default, then
        # a sanitized fingerprint. Never falls back to fault paths or generic runtime text.
        needle = (args.text or "").strip()
        if not needle:
            raise SearchError("intentional-flow-error mode requires --text")
        fingerprint = message_fingerprint(needle)
        for document in candidates:
            for error in document["intentionalErrors"]:
                kind = None
                if error["messageTemplate"].strip() == needle:
                    kind = "exact-source-message"
                elif error.get("resolvedDefaultText") and error["resolvedDefaultText"].strip() == needle:
                    kind = "exact-resolved-label"
                elif error.get("elementApiName") and error["elementApiName"] == needle:
                    kind = "element-api-name"
                elif (
                    fingerprint
                    and fingerprint != MERGE_PLACEHOLDER
                    and fingerprint in {error["fingerprint"], error.get("resolvedFingerprint")}
                ):
                    kind = "safe-fingerprint"
                if kind:
                    hit = hit_of(document, 1.0, [{"field": "intentionalError", "match": kind, "value": needle}], kind)
                    hit["intentionalError"] = {
                        "elementApiName": error["elementApiName"],
                        "elementLabel": error["elementLabel"],
                        "presentation": error["presentation"],
                        "reachability": error["reachability"],
                        "basis": "source-declared",
                        "note": (
                            "Source declares this template on the named element; this does not "
                            "attribute any org runtime error to this Flow (contract §8.2)."
                        ),
                        "limitations": error["limitations"],
                    }
                    results.append(hit)
        if not results:
            gaps.append("No intentional Flow error matched.")
    elif args.relation_anchor:
        # incoming (default): who points AT the anchor — "which automations write this field".
        # outgoing: what the anchor itself declares — "what does this Flow touch".
        anchor = args.relation_anchor
        direction = args.direction or "incoming"
        served_relation_kinds: set[str] = set()
        if direction == "incoming":
            scan = documents.load_many(sorted(documents.relation_ids(anchor) & candidate_ids))
        else:
            anchor_ids = ({anchor} & set(documents.posting_file("offsets"))) | documents.facet_ids("fullName", anchor)
            scan = documents.load_many(sorted(anchor_ids & candidate_ids))
        for document in scan:
            is_anchor = anchor in {document["identity"], document["facets"]["fullName"]}
            if direction == "outgoing" and not is_anchor:
                continue
            for edge in document["edges"]:
                if args.relation_kind and edge["kind"] != args.relation_kind:
                    continue
                if not args.include_heuristic and edge["assurance"] != "source-exact":
                    excluded["heuristicEdge"] += 1
                    continue
                if direction == "incoming" and edge["target"] != anchor:
                    continue
                # One row per EDGE, in both directions. The incoming branch used to `break`
                # after the first matching edge, so a Flow that both reads and writes the same
                # object was one row here and two rows from `explain`, `impact` and `context` —
                # golden question (d) answering differently depending on which command you ask.
                # An entry that touches an anchor twice is two facts about it.
                served_relation_kinds.add(edge["kind"])
                results.append(
                    hit_of(
                        document,
                        1.0,
                        [
                            {
                                "field": "relations.target",
                                "match": "exact-relation",
                                "relationKind": edge["kind"],
                                "value": edge["target"],
                            }
                        ],
                        "exact-relation",
                    )
                )
        # Golden question (d) is normally asked HERE — "which permission sets grant edit on this
        # field" is a relation query, not an `explain` — and this was the one relation surface
        # that never raised the collector's truncation disclosure. `explain`, `impact` and
        # `context` all did, so the same question answered clean or capped depending on which
        # command you happened to use. The kind filter is the caller's own when they named one,
        # otherwise the kinds actually served: a kind-less query asked about everything, so it
        # must hear about every capped family, including when the cap is why nothing matched.
        gaps.extend(truncation_gaps(
            documents,
            {args.relation_kind} if args.relation_kind else served_relation_kinds,
        ))
        if not results:
            gaps.append(
                "No exact relation edge matched; heuristic edges are excluded unless "
                "--include-heuristic is set, and absence of an edge is not proof of absence."
            )
    elif args.identity:
        wanted = {args.identity} & set(documents.posting_file("offsets"))
        wanted |= documents.facet_ids("fullName", args.identity)
        for document in documents.load_many(sorted(wanted & candidate_ids)):
            results.append(
                hit_of(document, 1.0, [{"field": "identity", "match": "exact-identity", "value": args.identity}], "exact-identity")
            )
        if len({hit["artifactId"] for hit in results}) > 1 and args.namespace is None:
            return {
                "outcome": "AMBIGUOUS",
                "interpretedQuery": interpreted,
                "reason": "identity exists in multiple namespaces; pass --namespace to disambiguate",
                "candidates": sorted(hit["artifactId"] for hit in results),
                "indexGeneration": manifest["generation"],
            }
    elif args.text:
        tokens = analyze(args.text)
        scored = bm25f(documents, candidates, tokens)
        match_class = "lexical"
        for document in candidates:
            if document["identity"] in scored:
                score, matched = scored[document["identity"]]
                results.append(hit_of(document, score, matched, "structured-plus-lexical" if facets else "lexical"))
        results.sort(key=lambda hit: (-hit["score"], hit["artifactId"]))
        # F2: derived from `scored`, never from hit["matchedOn"] — hit_of truncates that to 8,
        # so a discriminating term can contribute and still be invisible there.
        contributing = {row["value"] for _score, matched in scored.values() for row in matched}
        discriminating = {row["term"] for row in query_terms if row["matched"] and not row["saturated"]}
        unmatched = sorted(row["term"] for row in query_terms if not row["matched"])
        if results and not (contributing & discriminating):
            gaps.append(
                "Nothing discriminating matched: "
                + (f"no entry contains {', '.join(unmatched)}; " if unmatched else "")
                + f"every term that scored ({', '.join(sorted(contributing))}) appears in at "
                f"least {int(DF_SATURATION * 100)}% of this corpus and cannot rank anything. "
                "Serving these results would be relevance manufactured by function words — "
                "see queryTerms for the per-term evidence."
            )
            results = []
        elif results and unmatched:
            gaps.append(
                f"No entry contains: {', '.join(unmatched)}. Results rank on the remaining "
                "terms only; if one of these named the thing you meant, this is a coverage "
                "gap, not an answer."
            )
        if lexical_truncated:
            gaps.append(
                f"Lexical candidate set capped at {LEXICAL_CANDIDATE_CAP}; {lexical_truncated} "
                "lower-signal matches were not ranked. Narrow with a facet or a rarer term."
            )
        if not results:
            if lexical_token_ids:
                gaps.append(
                    f"{len(lexical_token_ids)} entr(ies) matched this query lexically and were then "
                    "excluded — see `excludedCounts` for by what. This is NOT an absence of matching "
                    "knowledge; add --state draft or relax a facet to see them."
                )
            else:
                gaps.append(
                    "No lexical match; try --state draft, relax a facet, or check the analyzer aliases."
                )
    else:
        results = [hit_of(document, 0.0, [], "structured") for document in candidates]
        results.sort(key=lambda hit: hit["artifactId"])

    # Ranked by the query, not by the alphabet. This list was `sorted(lane_ids(["draft"]))[:10]`
    # — byte-identical for an exact API name and for gibberish, printed where results go, on a
    # store where every entry is draft and so every first query lands here.
    draft_lane: list[dict[str, Any]] = []
    draft_basis = "none"
    if "draft" not in states:
        draft_ids = documents.lane_ids(["draft"])
        if args.text and lexical_token_ids:
            draft_ids = draft_ids & lexical_token_ids
        draft_documents = documents.load_many(sorted(draft_ids)[:LEXICAL_CANDIDATE_CAP])
        if args.text and draft_documents:
            draft_scored = bm25f(documents, draft_documents, analyze(args.text))
            ranked = sorted(
                (
                    (draft_scored[document["identity"]][0], document["identity"], document,
                     draft_scored[document["identity"]][1])
                    for document in draft_documents
                    if document["identity"] in draft_scored
                ),
                key=lambda row: (-row[0], row[1]),
            )
            draft_lane = [
                hit_of(document, score, matched, "draft-lane")
                for score, _identity, document, matched in ranked
            ][:10]
            draft_basis = "query-ranked"
        else:
            draft_lane = [
                hit_of(document, 0.0, [], "draft-lane") for document in draft_documents[:10]
            ]
            draft_basis = "alphabetical, no text query"
    relaxations = []
    if not results:
        if args.metadata_type:
            relaxations.append("remove --metadata-type")
        if facets:
            relaxations.append("remove one facet")
        if "draft" not in states and draft_lane:
            relaxations.append("add --state draft (separate lane, never merged with approved)")
        if args.relation_anchor and not args.include_heuristic:
            relaxations.append("add --include-heuristic (separate assurance lane)")

    if not results and args.identity:
        # An exact identity that matched nothing is either absent or lane-filtered, and those are
        # very different answers. Reporting neither — an empty result with an empty gaps array —
        # is the worst of the three: it reads as "no such thing" when the entry is sitting in the
        # index, revoked or drifted, one --state away.
        known = documents.get(args.identity)
        if known is not None:
            gaps.append(
                f"{args.identity} exists in this index in lane '{known['lane']}', which is outside "
                f"the requested {', '.join(states)}. It was not served. Pass --state {known['lane']} "
                "to see it, in its own bucket — it is not approved-current knowledge."
            )
        else:
            gaps.append(
                f"No entry in this index generation projects {args.identity}. That is absence of "
                "an ENTRY, not absence of the artifact."
            )

    served, hydration_gaps = hydrate(results[: args.top])
    gaps.extend(hydration_gaps)
    # `--state draft` (or any other lane opt-in) must not tip non-current content into a key
    # named `approvedResults`: a consumer reading that key is entitled to treat every hit in
    # it as effective approved knowledge. Opted-in lanes are served in their own bucket, each
    # hit still carrying its `lifecycle`.
    if excluded.get("heuristicEdge") and not args.include_heuristic:
        # Reporting the count only in excludedCounts was survivable while almost nothing was
        # excluded. Once kind-level heuristics are marked honestly, a default relation query
        # drops most of the graph — 44 of 50 edges for a hub object in the probe corpus — and a
        # silently narrowed answer reads exactly like a complete one.
        gaps.append(
            f"{excluded['heuristicEdge']} heuristic edge(s) were excluded; they are inferred "
            "(regex-derived), not declared. Add --include-heuristic to see them, in their own "
            "assurance lane."
        )
    current = [hit for hit in served if hit["lifecycle"] == "approved-current"]
    non_current = [hit for hit in served if hit["lifecycle"] != "approved-current"]
    if non_current:
        lanes = sorted({hit["lifecycle"] for hit in non_current})
        gaps.append(
            f"{len(non_current)} result(s) served from opted-in lane(s) {', '.join(lanes)}; "
            "they are not approved-current knowledge and must not be cited as effective."
        )
    gaps.append(ROW_LIFECYCLE_DISCLOSURE)
    return {
        "outcome": "OK" if served else "NO_MATCH",
        "interpretedQuery": interpreted,
        "queryTerms": query_terms,
        # `search` has no anchor: every hit is a row, including the one named by --identity, so
        # there is nothing here that was re-checked against the working tree.
        "lifecycleBasis": {"anchor": "not-applicable", "rows": LIFECYCLE_BASIS},
        "approvedResults": current,
        "nonCurrentResults": non_current,
        "draftCandidates": [hit["artifactId"] for hit in draft_lane][:10],
        "draftCandidatesBasis": draft_basis,
        "excludedCounts": dict(sorted(excluded.items())),
        "facetCounts": {
            "metadataType": manifest["metadataTypeCounts"],
            "lifecycle": manifest["laneCounts"],
        },
        "suggestedRelaxations": relaxations,
        "gaps": gaps,
        "matchClass": match_class,
        "indexGeneration": manifest["generation"],
    }


def source_coverage(manifest: dict[str, Any]) -> dict[str, Any]:
    """What could possibly have appeared as an edge source in this result.

    Only entry-homed types produce entries, so Profile, Layout, FlexiPage, ApprovalProcess,
    Workflow, DuplicateRule and the rest can never appear as a source however many of them
    reference the anchor. A field referenced only by a Profile and a Layout reports zero
    incoming edges — which reads as "nothing depends on it" unless the population is stated."""

    return {
        "entryHomedTypes": sorted(store.PROFILES),
        "inCorpus": manifest.get("metadataTypeCounts", {}),
        "note": (
            "Only the metadata types listed in entryHomedTypes can appear as an edge source. "
            "The generic-bucket remainder (Settings, Letterhead, Group, Network, Certificate, "
            "Document, Territory2 and similar label-only types) is structurally absent from "
            "this result."
        ),
    }


# What the collector actually writes into `typeFacts.truncatedFamilies` is the set of RELATION
# KINDS it dropped (`{kind for _, kind, _ in prioritized[max_usage_refs:]}` in
# force_app_knowledge._parse_access_bundle), not the XML family names. Keying this map on
# `fieldPermissions`/`objectPermissions` meant no key ever matched, so the relevance filter below
# was dead: the mandatory truncation gap fired on every query that touched a capped PermissionSet
# whatever it had asked about, which is noise, and noise is how a mandatory disclosure stops being
# read. Keys are therefore the emitted kinds; the value is the set of kinds that share the dropped
# kind's XML family, because the cap cuts a whole family at one priority — a caller asking about
# `grants-field-read` is affected by a `grants-field-edit` cut just as much.
FIELD_GRANT_KINDS = {"grants-field-read", "grants-field-edit", "grants-field-permission"}
OBJECT_GRANT_KINDS = {
    "grants-object-permission", "grants-object-view-all", "grants-object-modify-all",
}
TRUNCATION_FAMILY_KINDS = {
    "grants-field-read": FIELD_GRANT_KINDS,
    "grants-field-edit": FIELD_GRANT_KINDS,
    "grants-object-permission": OBJECT_GRANT_KINDS,
    "grants-object-view-all": OBJECT_GRANT_KINDS,
    "grants-object-modify-all": OBJECT_GRANT_KINDS,
    "grants-record-type": {"grants-record-type"},
    "grants-class-access": {"grants-class-access"},
    "grants-custom-permission": {"grants-custom-permission"},
    "grants-flow-access": {"grants-flow-access"},
    "grants-user-permission": {"grants-user-permission"},
}


def truncation_gaps(documents: "DocumentStore", kinds: Iterable[str]) -> list[str]:
    """Warn when a kind in this result belongs to a family some source had capped.

    A missing grant is indistinguishable from an absent grant, and the collector cuts
    fieldPermissions first — so the security question fails closed in the wrong direction
    unless the incompleteness is stated.

    A dropped kind this build does not recognise still raises the gap: an unknown truncation is
    exactly the case where staying quiet is unsafe."""

    truncated = documents.posting_file("reverse").get("truncatedSources", {})
    if not truncated:
        return []
    wanted = set(kinds)
    gaps = []
    for dropped, sources in sorted(truncated.items()):
        family_kinds = TRUNCATION_FAMILY_KINDS.get(dropped)
        if wanted and family_kinds and not (wanted & family_kinds):
            continue
        gaps.append(
            f"{len(sources)} entr(y/ies) had their {dropped} edge list capped by the collector; "
            "edges of that family may be missing from this result and absence is not proof of "
            "absence."
        )
    return gaps


# R5 for the one staleness window neither mechanism covers. `corpus_fingerprint` stamps entry
# files and the ledger; `hydrate` re-digests the ENTRY file. Nothing under force-app/ is in
# either, so appending one line to a Flow makes `knowledge_store.compute_lane` return
# `approved-drifted` immediately while every retrieval surface goes on serving the entry as
# approved-current, hydrated, with no gap, until the next `build`. The blast radius is bounded —
# the citation boundary reads compute_lane, so such an entry cannot be BOUND as a verified
# entryRef — but `context --identity` is the documented step-1 lookup for all eight Set A
# consumer surfaces, and it was reporting a lane the store disagreed with.
#
# The ANCHOR is re-checked against the working tree on every call (`verify_anchor`). The ROWS are
# not: §4.2 spent two rounds removing per-file work from the per-query path because it cost
# ~174 ms per invocation at 15 k, and re-hashing every served row's fragments would spend exactly
# what that bought. So the window is stated instead of implied — which is what R5 asks for and
# what silence was not.
LIFECYCLE_BASIS = "index-fresh"
ROW_LIFECYCLE_DISCLOSURE = (
    "Row `lifecycle` labels are index-fresh, not store-fresh: each was computed when this "
    "generation was built, and an edit under force-app/ moves an entry to `approved-drifted` in "
    "the store without touching the entry file or the ledger, so nothing invalidates this index. "
    "Only the anchor is re-checked against the working tree on every call. Re-run "
    "`python scripts/knowledge_search.py build` for row-level currency."
)


def source_drift_gaps(document: dict[str, Any]) -> list[str]:
    """Recorded source fragments whose bytes no longer match the working tree.

    This is the store's `approved-drifted` test (`regenerate_fragment_digest`), applied to one
    document so the cost is bounded and predictable: one hash per recorded fragment, and an entry
    records one to three. The anchor gets it because the anchor is the row a caller is most
    likely to act on; the plan's own safety argument puts the check here rather than in the
    fingerprint — "correctness rests on hydration, not on the fingerprint".

    Named fragments, not a bare boolean: "your entry is stale" that cannot say which file moved
    sends the reader to re-read the whole component.
    """

    drifted: list[str] = []
    for fragment in document.get("sources") or []:
        path = store.ROOT / fragment["path"]
        try:
            actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            drifted.append(f"{fragment['path']} (gone)")
            continue
        if actual != fragment["digest"]:
            drifted.append(fragment["path"])
    if not drifted:
        return []
    return [
        f"{document['identity']} is served from this index as lane '{document['lane']}', but "
        f"{len(drifted)} of the source fragment(s) it was approved against changed in the "
        f"working tree ({', '.join(drifted)}). The store computes 'approved-drifted' for it "
        "right now — the index is a disposable cache and is wrong about this entry. Re-run "
        "`python scripts/knowledge_search.py build` before citing it."
    ]


def verify_anchor(document: dict[str, Any], states: list[str]) -> list[str]:
    """Gaps a caller must see before trusting the anchor's own projection.

    The lane filter and hydration were applied to an artifact's EDGES and never to the artifact
    itself, so `explain` and `context` served a revoked, drifted or silently tampered entry in
    full — with its citation block, and its stale entryDigest — while `search` refused the same
    entry. `context` is the step-1 lookup for eight consumer surfaces, so this was the widest
    path by which the disposable index could be mistaken for authority.

    Source drift is the third state, and it was invisible to all of them: see
    `source_drift_gaps`.
    """

    gaps: list[str] = []
    if document["lane"] not in states:
        gaps.append(
            f"ANCHOR: {document['identity']} is in lane '{document['lane']}', outside the "
            f"requested {', '.join(states)}. Its facts are shown for inspection and are NOT "
            "approved-current knowledge — do not cite them as effective."
        )
    served, hydration_gaps = hydrate(
        [{"artifactId": document["identity"], "citation": document["citation"]}]
    )
    gaps.extend(f"ANCHOR: {gap}" for gap in hydration_gaps)
    # Two preconditions, both load-bearing. Hydration first: until the entry file is proved
    # unchanged the projection's record of its own fragments is itself in question, and "rebuild
    # the index" already is the answer — a second, weaker finding about a file we just refused is
    # noise. And `approved-current` only: that is the one lane where the index and the store can
    # disagree, because `compute_lane` moves nothing else on a source edit. Running it on a draft
    # would report drift the store does not recognise, against an entry nobody has approved yet.
    if served and document["lane"] == "approved-current":
        gaps.extend(f"ANCHOR: {gap}" for gap in source_drift_gaps(document))
    return gaps


def lane_split(rows: list[dict[str, Any]], key: str = "lifecycle") -> tuple[list, list]:
    """approved-current rows and opted-in-lane rows, never merged into one array."""
    current = [row for row in rows if row.get(key) == "approved-current"]
    other = [row for row in rows if row.get(key) != "approved-current"]
    return current, other


def lane_gaps(rows: list[dict[str, Any]], noun: str) -> list[str]:
    """Two different findings that `lane_split` puts in the same bucket, worded apart.

    A traversal row with `lifecycle: None` is a node with NO entry at all — a bare field token,
    an EventBus name, a UnitOfWork class nobody has drafted — and `lane_split` files it with the
    revoked and drifted rows, so the gap called it "served from opted-in lane(s); not
    approved-current knowledge". That reads as "an entry exists and you opted into its lane",
    which is the opposite of the truth. `search` already tells the two apart (commit f35b959);
    this is the same distinction on the traversal surfaces."""

    opted_in = [row for row in rows if row.get("lifecycle") is not None]
    unresolved = [row for row in rows if row.get("lifecycle") is None]
    gaps: list[str] = []
    if opted_in:
        gaps.append(
            f"{len(opted_in)} {noun} served from opted-in lane(s); they are not approved-current "
            "knowledge and must not be cited as effective."
        )
    if unresolved:
        gaps.append(
            f"{len(unresolved)} {noun} carry `resolved: false`: no entry in this index generation "
            "projects them, so nothing was re-read for them and they carry no lane at all. That "
            "is absence of an ENTRY, not absence of the artifact."
        )
    return gaps


def group_by_kind(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Edge rows keyed by relation kind, as §5 words the composed pack's sections.

    A flat array sorted by kind is not the same answer: an agent composing `incoming` cannot
    tell a declared `writes-field` row from an inferred `object-token` one without reading every
    row, and "which automations write this field" becomes a scan the caller has to perform."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["kind"]].append(row)
    return {kind: grouped[kind] for kind in sorted(grouped)}


def _requested_states(args: argparse.Namespace) -> list[str]:
    return list(getattr(args, "state", None) or ESTABLISHED_STATES)


def run_explain(args: argparse.Namespace) -> dict[str, Any]:
    documents, manifest = load_index()
    document = documents.get(args.identity)
    if document is None:
        raise SearchError(f"no entry projection for {args.identity}")
    states = _requested_states(args)
    allowed = documents.lane_ids(states)
    include_heuristic = bool(getattr(args, "include_heuristic", False))
    top = int(getattr(args, "top", None) or EXPLAIN_TOP_DEFAULT)

    # Incoming edges come from the reverse posting rather than a full-corpus scan, and carry
    # their lane so a revoked or tampered entry cannot be served as a dependency.
    rows: list[dict[str, Any]] = []
    excluded = {"lifecycle": 0, "heuristicEdge": 0}
    seen_targets = {document["identity"], document["facets"].get("fullName")}
    for target in sorted(name for name in seen_targets if name):
        for edge in documents.incoming_edges(target, include_heuristic=True):
            if edge["assurance"] != relation_kinds.SOURCE_EXACT and not include_heuristic:
                excluded["heuristicEdge"] += 1
                continue
            if edge["source"] not in allowed:
                excluded["lifecycle"] += 1
                continue
            source = documents.get(edge["source"])
            rows.append({**edge, "lifecycle": source["lane"] if source else None})
    rows.sort(key=lambda item: (item["source"], item["kind"], item["assurance"]))
    current, non_current = lane_split(rows)
    # Each lane is capped on its own: sharing one budget lets a burst of revoked rows push the
    # approved ones out of the answer, which is the opposite of what the lane split is for.
    dropped = max(0, len(current) - top) + max(0, len(non_current) - top)
    current, non_current = current[:top], non_current[:top]

    gaps: list[str] = []
    if excluded["heuristicEdge"]:
        gaps.append(
            f"{excluded['heuristicEdge']} heuristic edge(s) excluded; add --include-heuristic."
        )
    if excluded["lifecycle"]:
        gaps.append(
            f"{excluded['lifecycle']} edge(s) came from entries outside {', '.join(states)}."
        )
    if non_current:
        gaps.append(
            f"{len(non_current)} incoming edge(s) are declared by entries in opted-in lane(s); "
            "they are not approved-current knowledge and must not be cited as effective."
        )
    if dropped:
        # R5: explain was the one traversal surface that neither capped nor disclosed, so a hub
        # object returned 70 rows and looked complete at any number.
        gaps.append(
            f"{dropped} incoming edge(s) beyond --top {top} were not returned; this list is a "
            "sample, not the population."
        )
    gaps.extend(truncation_gaps(documents, {row["kind"] for row in rows}))
    gaps.extend(verify_anchor(document, states))
    gaps.append(ROW_LIFECYCLE_DISCLOSURE)

    # `parts` went through none of this: not lane-filtered, not capped. It served revoked
    # entries as parts of an approved object with no marker at all.
    parts_all = [
        row for row in documents.incoming_edges(
            document["facets"].get("fullName") or document["identity"],
            kinds={CONTAINMENT_KIND}, include_heuristic=include_heuristic,
        )
        if row["source"] in allowed
    ]
    parts = sorted(parts_all, key=lambda row: row["source"])[:top]
    if len(parts_all) > len(parts):
        gaps.append(f"{len(parts_all) - len(parts)} part(s) beyond --top {top} were not returned.")

    return {
        "outcome": "EXPLAIN",
        "artifactId": document["identity"],
        "lifecycle": document["lane"],
        # The anchor's own lane is store-fresh (verify_anchor re-checks the file AND its source
        # fragments); every row's is not. One field, so a consumer never has to infer which.
        "lifecycleBasis": {"anchor": "store-fresh", "rows": LIFECYCLE_BASIS},
        "facets": document["facets"],
        "purpose": document.get("purpose"),
        "purposeBasis": (
            "the entry's Purpose prose, served whole; cite citation.path + "
            "citation.entryDigest, not this field"
        ),
        "assurance": document["assurance"],
        "coverage": document["coverage"],
        "limitations": document["limitations"],
        "outgoing": document["edges"],
        "incoming": current,
        "incomingNonCurrent": non_current,
        "parts": parts,
        "sourceCoverage": source_coverage(manifest),
        "excludedCounts": excluded,
        "gaps": gaps,
        "counts": {"documentReads": documents.document_reads, "postingBytesRead": documents.posting_bytes},
        "intentionalErrors": [
            {
                "elementApiName": error["elementApiName"],
                "presentation": error["presentation"],
                "reachability": error["reachability"],
                "basis": "source-declared",
            }
            for error in document["intentionalErrors"]
        ],
        "citation": document["citation"],
        "indexGeneration": manifest["generation"],
    }


def traverse(
    documents: "DocumentStore",
    anchor: str,
    *,
    depth: int,
    direction: str,
    allowed: set[str],
    include_heuristic: bool,
    stop_at: set[str] | None = None,
) -> dict[str, Any]:
    """Breadth-first walk from one anchor, returning the node set and how each was reached.

    `stop_at` is the caller's stop-list, matched against a reached node's identity AND its
    `fullName`: such a node is kept as an edge target and never expanded through (feature
    `hubs`, contract §13.1). `depth` is honoured exactly — `depth=0` walks no levels at all,
    which is what "anchors only" has to mean for the caller that offers its anchors itself.

    Extracted from run_impact so `impact`, `context` and (next) feature membership share one
    traversal rather than three. Three implementations of a bounded, lane-filtered,
    assurance-aware BFS would drift, and the plan's "one traversal vocabulary" rule exists
    because the first two already had different limit names.

    Returns nodes with `path` (the chain that reached them) and `minAssurance` (the weakest hop
    in that chain — a chain is only as trustworthy as its weakest link), plus the exclusion
    counters, which limits were hit, and `observed` — the high-water marks the limits are set
    against. Nodes with no entry are kept and marked `resolved: False`; dropping an unresolvable
    hop would make a partial graph look complete.

    `observed` is what makes TRAVERSAL_LIMITS derivable rather than asserted: the benchmark reads
    the real fanout and node counts off this walk instead of reimplementing it, so the numbers in
    the table are produced by the code that enforces them.
    """

    started = time.monotonic()
    excluded = {"lifecycle": 0, "heuristicEdge": 0}
    # WHO was dropped, not only how many. The count alone let `compute_membership` discard the
    # identities, so a walk emptied by the default lane filter was indistinguishable from a walk
    # that reached nothing. Reporting only — an excluded node is still never expanded through,
    # and nothing here may ever join a digest input.
    excluded_identities: set[str] = set()
    limits_hit: set[str] = set()
    observed_fanout = 0
    # `path` carries how a node was reached. A flat hop-2 row names an edge target that is only
    # accidentally connectable to the anchor, so a reader cannot tell a real chain from a
    # coincidence of naming.
    chains: list[dict[str, Any]] = []
    visited = {anchor}
    # Nodes the stop-list kept but did not expand, and the stop-list entries that actually fired.
    # `halted` joins `visited` so a stop node is offered once, not once per branch that reaches it;
    # `stopped_names` is reported, because a boundary that silently drops a hop reads as a boundary
    # that had nothing there.
    halted: set[str] = set()
    stopped_names: set[str] = set()
    frontier = [{"node": anchor, "path": [], "minAssurance": relation_kinds.SOURCE_EXACT}]

    for level in range(depth):
        next_frontier: list[dict[str, Any]] = []
        for item in sorted(frontier, key=lambda entry: entry["node"]):
            # The clock, checked once per expanded node rather than per hop: the node count is
            # what bounds this loop, so one `monotonic()` per iteration is O(nodes) and cannot
            # itself become the cost. A limit expressed only in nodes cannot bound a walk whose
            # nodes are individually expensive — a hub whose fanout is capped 500 times over
            # still does 500 posting reads per level — so the terminator nobody could hit was
            # the one that mattered.
            if time.monotonic() - started > TRAVERSAL_LIMITS["maxSeconds"]:
                limits_hit.add("time")
                break
            document = documents.get(item["node"])
            names = {item["node"]}
            if document:
                full_name = document["facets"].get("fullName")
                if full_name:
                    names.add(str(full_name))
            hops = []
            if direction == "incoming":
                for name in sorted(names):
                    for edge in documents.incoming_edges(name, include_heuristic=True):
                        hops.append((edge["source"], edge["kind"], name, edge["assurance"], False))
                # An object is reached ONLY through the containment edge of one of its own parts,
                # and that edge points away from an incoming walk. Without this hop no object but
                # an anchor could ever be reached: measured on a real boundary, `Service_Task__c`,
                # `Time_Log__c`, `Ticket_Comment__c` and `Category__c` were all absent while their
                # own fields were members, identically at depth 1, 2 and 3 — so `depth` bought
                # nothing and `hubs` had no hop to stop. The inversion already existed twice, in
                # `run_explain` and `run_context`; it was missing from the shared walk.
                for edge in (document or {}).get("edges", []):
                    if edge["kind"] != CONTAINMENT_KIND:
                        continue
                    row = documents.target_row(edge["target"])
                    hops.append((
                        row.get("targetIdentity") or edge["target"],
                        edge["kind"], edge["target"], edge["assurance"], True,
                    ))
            else:
                for edge in (document or {}).get("edges", []):
                    row = documents.target_row(edge["target"])
                    resolved = row.get("targetIdentity")
                    hops.append((resolved or edge["target"], edge["kind"], edge["target"], edge["assurance"], False))
            observed_fanout = max(observed_fanout, len(hops))
            if len(hops) > TRAVERSAL_LIMITS["maxFanout"]:
                limits_hit.add("fanout")
                hops = sorted(hops)[: TRAVERSAL_LIMITS["maxFanout"]]
            for node, kind, via, assurance, owner_ward in sorted(hops):
                if assurance != relation_kinds.SOURCE_EXACT and not include_heuristic:
                    excluded["heuristicEdge"] += 1
                    continue
                reached = documents.get(node)
                if reached is None:
                    # Forward hop into something with no entry: kept, labelled, never dropped.
                    lifecycle = None
                elif node not in allowed:
                    excluded["lifecycle"] += 1
                    excluded_identities.add(node)
                    continue
                else:
                    lifecycle = reached["lane"]
                if node in visited:
                    continue
                weakest = (
                    relation_kinds.SOURCE_DERIVED_HEURISTIC
                    if relation_kinds.SOURCE_DERIVED_HEURISTIC in (assurance, item["minAssurance"])
                    else relation_kinds.SOURCE_EXACT
                )
                step = {"from": item["node"], "kind": kind, "to": node, "via": via, "assurance": assurance}
                if owner_ward:
                    # The containment edge was followed towards the OWNER, not towards the part.
                    # `kind` stays honest — it is the same `belongs-to` edge — so the direction has
                    # to be on the step, or a reader cannot tell "contains a member" from
                    # "is a member's part" and the membership reason inverts.
                    step["ownerWard"] = True
                chains.append({
                    "node": node, "hop": level + 1, "lifecycle": lifecycle,
                    "resolved": reached is not None,
                    "path": item["path"] + [step],
                    "minAssurance": weakest,
                })
                reached_names = {node}
                if reached is not None:
                    reached_full = reached["facets"].get("fullName")
                    if reached_full:
                        reached_names.add(str(reached_full))
                hit = reached_names & stop_at if stop_at else set()
                if hit:
                    stopped_names |= hit
                    halted.add(node)
                else:
                    next_frontier.append({"node": node, "path": item["path"] + [step], "minAssurance": weakest})
                if len(chains) >= TRAVERSAL_LIMITS["maxNodes"]:
                    limits_hit.add("nodes")
                    break
            if limits_hit & {"nodes", "time"}:
                break
        visited |= {row["node"] for row in next_frontier} | halted
        frontier = next_frontier
        if not frontier or limits_hit & {"nodes", "time"}:
            break

    chains.sort(key=lambda row: (row["hop"], row["node"]))
    return {
        "nodes": chains,
        "excluded": excluded,
        "excludedIdentities": sorted(excluded_identities),
        "stoppedAt": sorted(stopped_names),
        "limitsHit": limits_hit,
        # Deliberately free of any elapsed time: downstream digests consume what this walk produces,
        # and a clock reading in the return value would make two identical walks compare unequal.
        "observed": {"maxFanout": observed_fanout, "nodes": len(chains)},
    }


def run_impact(args: argparse.Namespace) -> dict[str, Any]:
    """Reverse or forward traversal from an anchor, one chain per reached node.

    Direction matters more than it looks. Reverse answers "what breaks if I change this" —
    who points at the anchor. Forward answers "how does this work" — what the anchor invokes,
    then what that invokes. Only reverse existed, so `impact` from an ApexTrigger returned zero
    edges: nothing references a trigger. The outgoing edges were on the projection the whole
    time; only the traversal was missing.

    The anchor gets the same scrutiny as the rows, for the reason `verify_anchor` documents: this
    surface applied the lane filter to reached NODES only, so a revoked or tamper-failing anchor
    produced a gap list byte-identical to the healthy one, and a served row nobody had re-read.
    """

    documents, manifest = load_index()
    limit = DEPTH_LIMITS["impact"]
    requested = int(getattr(args, "depth", 1) or 1)
    depth = max(1, min(requested, limit))
    direction = getattr(args, "direction", None) or "incoming"
    include_heuristic = bool(getattr(args, "include_heuristic", False))
    states = _requested_states(args)
    allowed = documents.lane_ids(states)
    top = int(getattr(args, "top", None) or IMPACT_TOP_DEFAULT)

    # The traversal walks by NAME, so the anchor may be a bare fullName rather than an entry
    # identity. It is resolved the way `context` resolves it before it can be verified at all.
    anchor_document = documents.get(args.identity)
    anchor_candidates: list[str] = []
    if anchor_document is None:
        anchor_candidates = documents.identities_for_full_name(args.identity)
        if len(anchor_candidates) == 1:
            anchor_document = documents.get(anchor_candidates[0])

    walk = traverse(
        documents, args.identity, depth=depth, direction=direction,
        allowed=allowed, include_heuristic=include_heuristic,
    )
    chains, excluded, limits_hit = walk["nodes"], walk["excluded"], walk["limitsHit"]
    served = chains[:top]
    if len(chains) > top:
        limits_hit.add("top")

    # Hydration runs over what SURVIVED the cap, so a served row is a re-read row. Nodes that
    # resolved to no entry stay in the answer marked unhydrated — dropping an unresolvable hop
    # would make a partial graph look complete — and there is nothing to re-read for them.
    served_ids = sorted({row["node"] for row in served if documents.get(row["node"])})
    hydrated, hydration_gaps = hydrate(
        [
            {"artifactId": identity, "citation": documents.get(identity)["citation"]}
            for identity in served_ids
        ]
    )
    verified = {hit["artifactId"] for hit in hydrated}
    for row in served:
        row["hydrated"] = row["node"] in verified
    current, non_current = lane_split(served)

    gaps: list[str] = list(hydration_gaps)
    if requested > limit:
        gaps.append(f"depth {requested} was reduced to the {limit}-hop limit for impact.")
    if excluded["heuristicEdge"]:
        gaps.append(
            f"{excluded['heuristicEdge']} heuristic hop(s) excluded. Execution chains are built "
            "from inferred edges (invokes-class is regex-derived), so answering \"how does this "
            "work\" needs --include-heuristic; each hop then carries its own assurance."
        )
    if excluded["lifecycle"]:
        gaps.append(f"{excluded['lifecycle']} node(s) outside {', '.join(states)} were excluded.")
    gaps.extend(lane_gaps(non_current, "node(s)"))
    if limits_hit:
        gaps.append(f"traversal limits reached: {', '.join(sorted(limits_hit))}.")
    gaps.extend(truncation_gaps(documents, {step["kind"] for row in served for step in row["path"]}))
    if anchor_document is not None:
        gaps.extend(verify_anchor(anchor_document, states))
    elif len(anchor_candidates) > 1:
        gaps.append(
            f"ANCHOR: {args.identity} is a bare name held by {len(anchor_candidates)} entries "
            f"({', '.join(sorted(anchor_candidates))}), so none of them was verified. Pass the "
            "full <MetadataType>:<ns|c>:<FullName> identity."
        )
    else:
        gaps.append(
            f"ANCHOR: no entry in this index generation projects {args.identity}, so the anchor "
            "itself is unverified — the walk descends from a name, not from approved knowledge. "
            "That is absence of an ENTRY, not absence of the artifact."
        )
    gaps.append(ROW_LIFECYCLE_DISCLOSURE)

    return {
        "outcome": "IMPACT",
        "anchor": args.identity,
        "anchorIdentity": anchor_document["identity"] if anchor_document else None,
        "anchorLifecycle": anchor_document["lane"] if anchor_document else None,
        "lifecycleBasis": {
            # A bare-name anchor has no entry to re-check, so nothing about it is store-fresh
            # and saying otherwise would be the laundering this disclosure exists to prevent.
            "anchor": "store-fresh" if anchor_document else "no-entry",
            "rows": LIFECYCLE_BASIS,
        },
        "direction": direction,
        "depthRequested": requested,
        "depthLimit": limit,
        "depthReached": max((row["hop"] for row in served), default=0),
        "limitsHit": sorted(limits_hit),
        "nodes": current,
        "nodesNonCurrent": non_current,
        "sourceCoverage": source_coverage(manifest),
        "excludedCounts": excluded,
        "gaps": gaps,
        "counts": {
            "documentReads": documents.document_reads,
            "postingBytesRead": documents.posting_bytes,
            "nodesServed": len(served),
        },
        "note": "Static source-declared edges only; absence of an edge is not proof of absence.",
        "indexGeneration": manifest["generation"],
    }


PERMISSION_KINDS = {
    kind for kinds in TRUNCATION_FAMILY_KINDS.values() for kind in kinds
} | {"grants-flow-access", "grants-custom-permission", "grants-user-permission"}
CONTEXT_TOP_DEFAULT = 25


def org_usage_bucket(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Org observation disclosure (contract §14.3), separate from every lane bucket.

    The projection carries only orgKey/environment/observedAt/expiresAt; expiry is recomputed
    against the wall clock ON EVERY READ — an index built yesterday must not serve
    yesterday's freshness. This bucket never carries probe numbers: values live in the entry
    and are summarized only by entry-status/entry-review, and the full org lane (superseded
    detection needs config + org ledger) is entry-status's verdict, not this one."""
    from datetime import datetime, timezone

    rows: list[dict[str, Any]] = []
    for block in document.get("orgUsage") or []:
        expired = True
        try:
            expired = datetime.now(timezone.utc) >= store._parse_iso(block["expiresAt"])
        except (KeyError, ValueError, TypeError):
            pass
        rows.append(
            {
                "orgKey": block.get("orgKey"),
                "status": (
                    "org-expired — treat as absent: run a live probe or re-attach, never cite"
                    if expired
                    else "current-by-clock — the full org lane needs entry-status before citing"
                ),
                "attribution": (
                    f"sandbox {block.get('orgKey')} ({block.get('environment')}), observed "
                    f"{block.get('observedAt')}, expires {block.get('expiresAt')} — "
                    "machine-attested, NOT covered by entry approval; shape/presence, "
                    "not production volume"
                ),
            }
        )
    return rows


def run_context(args: argparse.Namespace) -> dict[str, Any]:
    """Everything about one artifact, in one call.

    Answering "tell me about X" took six heterogeneous queries — identity lookup, a facet query
    per child type, incoming relations, outgoing relations, impact, permission grants — each
    with its own shape and its own lane semantics, and two of them (ValidationRule, RecordType)
    had no object facet at all, so the owner had to be read out of a fullName prefix by hand.

    Sections are capped BEFORE hydration, not after. Hydrating first and capping second spent
    the budget on rows the caller never sees and left the rows they are invited to cite
    unverified — inverting the point of the budget.

    `chains` is the sixth section §5 names and the reason this call replaces `impact` too: an
    execution chain used to need a second command. It is a traversal, so it takes `--direction`
    (§4.1) and, per R6, it is mostly a heuristic product — the default filter drops the hops and
    says so rather than returning a short chain that reads as a complete one.
    """

    documents, manifest = load_index()
    document = documents.get(args.identity)
    if document is None:
        candidates = documents.identities_for_full_name(args.identity)
        if len(candidates) == 1:
            document = documents.get(candidates[0])
        elif len(candidates) > 1:
            return {
                "outcome": "AMBIGUOUS",
                "query": args.identity,
                "candidates": sorted(candidates),
                "gaps": [
                    "A bare name that exists in several namespaces is never resolved by ranking; "
                    "pass the full <MetadataType>:<ns|c>:<FullName> identity."
                ],
                "indexGeneration": manifest["generation"],
            }
    if document is None:
        return {
            "outcome": "NO_ENTRY",
            "query": args.identity,
            "entryExists": False,
            "gaps": [
                f"No Knowledge Entry projects {args.identity} in this index generation. That is "
                "absence of an ENTRY, not absence of the artifact — check `entry-coverage` for "
                "the source-side denominator."
            ],
            "indexGeneration": manifest["generation"],
        }

    states = _requested_states(args)
    allowed = documents.lane_ids(states)
    include_heuristic = bool(getattr(args, "include_heuristic", False))
    direction = getattr(args, "direction", None) or "incoming"
    top = int(getattr(args, "top", None) or CONTEXT_TOP_DEFAULT)
    names = {document["identity"]}
    full_name = document["facets"].get("fullName")
    if full_name:
        names.add(str(full_name))

    incoming: list[dict[str, Any]] = []
    excluded = {"lifecycle": 0, "heuristicEdge": 0, "cap": 0}
    for name in sorted(names):
        for edge in documents.incoming_edges(name, include_heuristic=True):
            if edge["assurance"] != relation_kinds.SOURCE_EXACT and not include_heuristic:
                excluded["heuristicEdge"] += 1
                continue
            if edge["source"] not in allowed:
                excluded["lifecycle"] += 1
                continue
            source = documents.get(edge["source"])
            incoming.append({**edge, "lifecycle": source["lane"] if source else None})

    def bucket(rows: list[dict[str, Any]], kinds: set[str] | None, invert: bool = False):
        """One section, split into its lanes — never merged, per the rule `search` states.

        A consumer reading `parts` is entitled to treat every row in it as effective approved
        knowledge; a per-row `lifecycle` label does not earn that back, because the eight consumer
        surfaces that read this pack compose the array, not the labels. Each lane is capped on its
        own budget so a burst of revoked rows cannot push approved ones out of the answer."""

        chosen = [
            row for row in rows
            if kinds is None or ((row["kind"] in kinds) is not invert)
        ]
        chosen.sort(key=lambda row: (row["kind"], row["source"]))
        current, non_current = lane_split(chosen)
        excluded["cap"] += max(0, len(current) - top) + max(0, len(non_current) - top)
        return current[:top], non_current[:top]

    parts, parts_non_current = bucket(incoming, {CONTAINMENT_KIND})
    permissions, permissions_non_current = bucket(incoming, PERMISSION_KINDS)
    other_incoming, other_non_current = bucket(
        incoming, {CONTAINMENT_KIND} | PERMISSION_KINDS, invert=True
    )
    served_rows = (
        parts + parts_non_current + permissions + permissions_non_current
        + other_incoming + other_non_current
    )

    # `outgoing` was `document["edges"]` verbatim: neither capped by --top nor filtered by
    # --include-heuristic, while the exclusion gap counted incoming edges only. A default,
    # no-flag call therefore served 18 source-derived-heuristic outgoing edges next to a gap
    # line saying "1 heuristic edge(s) excluded". Nothing was laundered — every row carries its
    # assurance — but the default filter meant two different things in one answer.
    outgoing_rows: list[dict[str, Any]] = []
    for edge in document["edges"]:
        if edge["assurance"] != relation_kinds.SOURCE_EXACT and not include_heuristic:
            excluded["heuristicEdge"] += 1
            continue
        outgoing_rows.append(dict(edge))
    outgoing_rows.sort(key=lambda row: (row["kind"], row["target"]))
    excluded["cap"] += max(0, len(outgoing_rows) - top)
    outgoing_rows = outgoing_rows[:top]

    # §5's `chains`, and the only section that is a traversal rather than a posting read.
    walk = traverse(
        documents, document["identity"], depth=DEPTH_LIMITS["context"], direction=direction,
        allowed=allowed, include_heuristic=include_heuristic,
    )
    chain_excluded, chain_limits = walk["excluded"], set(walk["limitsHit"])
    chain_rows = walk["nodes"]
    if len(chain_rows) > top:
        chain_limits.add("top")
        chain_rows = chain_rows[:top]
    chains, chains_non_current = lane_split(chain_rows)

    # Hydration runs over what SURVIVED the cap, so a served row is a verified row. Chain nodes
    # join the same pass: they are rows the caller is invited to act on exactly like the edge
    # rows, and a node that resolves to no entry has nothing to re-read.
    served_sources = {row["source"] for row in served_rows}
    chain_nodes = {row["node"] for row in chain_rows}
    hydrated, hydration_gaps = hydrate(
        [
            {"artifactId": identity, "citation": documents.get(identity)["citation"]}
            for identity in sorted(served_sources | chain_nodes)
            if documents.get(identity)
        ]
    )
    verified = {hit["artifactId"] for hit in hydrated}
    for row in served_rows:
        row["hydrated"] = row["source"] in verified
    for row in chain_rows:
        row["hydrated"] = row["node"] in verified

    gaps = list(hydration_gaps)
    if excluded["heuristicEdge"]:
        gaps.append(
            f"{excluded['heuristicEdge']} heuristic edge(s) excluded across `incoming` and "
            "`outgoing`; they are inferred (regex-derived), not declared. Add "
            "--include-heuristic to see them, in their own assurance lane."
        )
    if chain_excluded["heuristicEdge"]:
        # R6: the mandatory disclosure. 58 of 59 forward-chain edges in the probe corpus are
        # `invokes-class`, so on the default filter this section is usually empty for the exact
        # question it exists to answer, and silence would read as "there is no chain".
        gaps.append(
            f"{chain_excluded['heuristicEdge']} heuristic hop(s) were dropped from `chains`. "
            "Execution chains are built from inferred edges (invokes-class is regex-derived), so "
            "answering \"how does this work\" needs --include-heuristic; each hop then carries "
            "its own assurance and each chain a path-level minAssurance."
        )
    if chain_excluded["lifecycle"]:
        gaps.append(
            f"{chain_excluded['lifecycle']} chain hop(s) led to entries outside "
            f"{', '.join(states)} and were not followed."
        )
    gaps.extend(lane_gaps(chains_non_current, "chain(s)"))
    if chain_limits:
        gaps.append(f"chain traversal limits reached: {', '.join(sorted(chain_limits))}.")
    if excluded["lifecycle"]:
        gaps.append(f"{excluded['lifecycle']} edge(s) came from entries outside {', '.join(states)}.")
    if excluded["cap"]:
        gaps.append(f"{excluded['cap']} row(s) beyond --top {top} were not returned.")
    gaps.append(
        "`parts` lists artifacts that have a Knowledge Entry in this index generation, not the "
        "object's declared composition. Run `python scripts/knowledge_store.py entry-coverage` "
        "for the source-side denominator."
    )
    gaps.extend(truncation_gaps(documents, {row["kind"] for row in incoming}))
    non_current = parts_non_current + permissions_non_current + other_non_current
    if non_current:
        gaps.append(
            f"{len(non_current)} row(s) come from entries in opted-in lane(s) and are served in "
            "the separate *NonCurrent buckets; each row also carries its own `lifecycle` — they "
            "are not approved-current knowledge and must not be cited as effective."
        )
    gaps.extend(verify_anchor(document, states))
    gaps.append(ROW_LIFECYCLE_DISCLOSURE)

    return {
        "outcome": "CONTEXT",
        "artifactId": document["identity"],
        "lifecycle": document["lane"],
        "lifecycleBasis": {"anchor": "store-fresh", "rows": LIFECYCLE_BASIS},
        "orgUsage": org_usage_bucket(document),
        "subject": {
            "facets": document["facets"],
            "purpose": document.get("purpose"),
            "assurance": document["assurance"],
            "coverage": document["coverage"],
            "limitations": document["limitations"],
            "citation": document["citation"],
        },
        "parts": parts,
        "partsNonCurrent": parts_non_current,
        "partsCoverage": {
            "basis": f"inverted {CONTAINMENT_KIND} edges in this index generation",
            "entriesByType": manifest.get("metadataTypeCounts", {}),
        },
        "permissions": permissions,
        "permissionsNonCurrent": permissions_non_current,
        "incoming": group_by_kind(other_incoming),
        "incomingNonCurrent": group_by_kind(other_non_current),
        "outgoing": group_by_kind(outgoing_rows),
        "chains": chains,
        "chainsNonCurrent": chains_non_current,
        "chainsMeta": {
            "direction": direction,
            "depth": DEPTH_LIMITS["context"],
            "limitsHit": sorted(chain_limits),
            "excluded": chain_excluded,
            "note": (
                "Each hop carries its own `assurance`; each chain carries `minAssurance`, the "
                "weakest hop in its path — a chain is only as trustworthy as that hop."
            ),
        },
        "intentionalErrors": document["intentionalErrors"],
        "sourceCoverage": source_coverage(manifest),
        "excludedCounts": excluded,
        "gaps": gaps,
        "counts": {
            "documentReads": documents.document_reads,
            "postingBytesRead": documents.posting_bytes,
        },
        "indexGeneration": manifest["generation"],
    }


EDGE_HEALTH_SAMPLE_CAP = 50


def run_edge_health(args: argparse.Namespace) -> dict[str, Any]:
    """How well edge targets resolve to entries in this index generation.

    Deliberately DISTINCT from `force_app_knowledge.py relation-health` and its
    entry_edge_health half, which answer a different question — "does this edge target still
    exist in force-app source?" — against the live tree. This surface answers "does the target
    have an entry in this index generation?". Neither report supersedes the other.
    """

    documents, manifest = load_index()
    reverse = documents.posting_file("reverse")
    by_target = reverse.get("byTarget", {})
    counts: dict[str, int] = defaultdict(int)
    for row in by_target.values():
        counts[row["resolution"]] += 1
    ambiguous = sorted(key for key, row in by_target.items() if row["resolution"] == "ambiguous")
    undecided = sorted(
        key for key, row in by_target.items()
        if row["resolution"] == "no-entry" and row.get("decidable")
    )
    gaps = []
    if len(ambiguous) > EDGE_HEALTH_SAMPLE_CAP:
        gaps.append(
            f"{len(ambiguous) - EDGE_HEALTH_SAMPLE_CAP} ambiguous target(s) beyond the "
            f"{EDGE_HEALTH_SAMPLE_CAP}-row sample are counted but not named."
        )
    if len(undecided) > EDGE_HEALTH_SAMPLE_CAP:
        gaps.append(
            f"{len(undecided) - EDGE_HEALTH_SAMPLE_CAP} decidable no-entry target(s) beyond the "
            f"{EDGE_HEALTH_SAMPLE_CAP}-row sample are counted but not named."
        )
    return {
        "outcome": "EDGE_HEALTH",
        "targets": len(by_target),
        "resolutionCounts": dict(sorted(counts.items())),
        # Only a decidable no-entry target is a documentation gap: an unnamespaced
        # __c/__e/__mdt/__b/__x name this package could hold an entry for. A standard object or
        # a packaged name has no entry by nature and its absence proves nothing.
        "decidableNoEntry": {
            "count": len(undecided),
            "targets": undecided[:EDGE_HEALTH_SAMPLE_CAP],
        },
        "ambiguous": {
            "count": len(ambiguous),
            "targets": ambiguous[:EDGE_HEALTH_SAMPLE_CAP],
        },
        # Computed since the reverse index existed, exposed nowhere until now: sources whose
        # own edge list was capped by the collector, per truncated family.
        "truncatedSources": reverse.get("truncatedSources", {}),
        "basis": (
            "resolution is against ENTRIES in this index generation. "
            "`force_app_knowledge.py relation-health` answers the different question of whether "
            "a target still exists in force-app source; neither report supersedes the other."
        ),
        "gaps": gaps,
        "indexGeneration": manifest["generation"],
    }


def run_capabilities(args: argparse.Namespace) -> dict[str, Any]:
    facets = dict(GLOBAL_FACETS)
    if args.metadata_type:
        facets.update(PROFILE_FACETS.get(args.metadata_type, {}))
    else:
        for profile_facets in PROFILE_FACETS.values():
            facets.update(profile_facets)
    return {
        "outcome": "CAPABILITIES",
        "metadataType": args.metadata_type,
        "facets": dict(sorted(facets.items())),
        "operators": list(FACET_OPERATORS),
        "modes": ["hybrid", "intentional-flow-error"],
        "lifecycleLanes": list(ALL_LANES),
        "defaultStates": list(ESTABLISHED_STATES),
        "analyzerVersion": ANALYZER_VERSION,
        "supportedProfiles": sorted(PROFILE_FACETS),
        # --relation-kind accepted any string and capabilities listed none, so the only way to
        # learn the vocabulary was to guess or read the collector.
        "relationKinds": sorted(relation_kinds.ALL_REF_KINDS),
        "heuristicRelationKinds": sorted(relation_kinds.HEURISTIC_REF_KINDS),
        "containmentKind": CONTAINMENT_KIND,
        "directions": ["incoming", "outgoing"],
        "depthLimits": dict(DEPTH_LIMITS),
        "assuranceLanes": {
            relation_kinds.SOURCE_EXACT: "declared in source; served by default",
            relation_kinds.SOURCE_DERIVED_HEURISTIC: (
                "inferred (regex-derived); excluded unless --include-heuristic. Execution chains "
                "are built from these, so answering \"how does this work\" requires the flag."
            ),
        },
        "feature": _feature_capabilities(),
    }


def _feature_capabilities() -> dict[str, Any]:
    """Feature Knowledge v2 vocabularies (contract §13): layers, roles, claim types and
    authority classes, published so nobody guesses an enum."""
    try:
        from scripts import feature_knowledge as fk
    except ModuleNotFoundError:
        import feature_knowledge as fk
    return {
        "layers": list(fk.LAYERS),
        "claimTypes": list(fk.CLAIM_TYPES),
        "humanAttestableClaimTypes": sorted(fk.HUMAN_ATTESTABLE_CLAIM_TYPES),
        "citableAuthorities": sorted(fk.CITABLE_AUTHORITIES),
        "operationKinds": {kind: list(ops) for kind, ops in fk.OPERATION_KINDS.items()},
        "bodySections": list(fk.BODY_SECTIONS),
        "coreBodySections": list(fk.CORE_BODY_SECTIONS),
    }


def command_build(args: argparse.Namespace) -> dict[str, Any]:
    return build_index(check=args.check, full=args.full)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge_search", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="rebuild the generated search cache")
    build.add_argument("--check", action="store_true")
    build.add_argument("--full", action="store_true", help="ignore reusable projections")
    build.set_defaults(func=command_build)

    search = commands.add_parser("search", help="typed retrieval over approved entries")
    search.add_argument("--text", default=None)
    search.add_argument("--identity", default=None)
    search.add_argument("--metadata-type", default=None)
    search.add_argument("--namespace", default=None)
    search.add_argument("--state", action="append", default=None, choices=list(ALL_LANES))
    search.add_argument("--facet", action="append", default=None, help="key[:op]=value")
    search.add_argument("--relation-anchor", default=None)
    search.add_argument("--relation-kind", default=None)
    search.add_argument("--direction", default=None, choices=["outgoing", "incoming"])
    search.add_argument("--include-heuristic", action="store_true")
    search.add_argument("--mode", default="hybrid", choices=["hybrid", "intentional-flow-error"])
    search.add_argument("--top", type=int, default=10)
    search.set_defaults(func=run_search)

    explain = commands.add_parser("explain", help="one artifact with usage and reverse usage")
    explain.add_argument("--identity", required=True)
    explain.add_argument("--state", action="append", default=None, choices=list(ALL_LANES))
    explain.add_argument("--top", type=int, default=EXPLAIN_TOP_DEFAULT)
    explain.add_argument("--include-heuristic", action="store_true")
    explain.set_defaults(func=run_explain)

    impact = commands.add_parser("impact", help="bounded dependency traversal, either direction")
    impact.add_argument("--identity", required=True)
    impact.add_argument("--depth", type=int, default=1)
    impact.add_argument(
        "--direction", default="incoming", choices=["incoming", "outgoing"],
        help="incoming: who points at the anchor (what breaks if I change it). "
        "outgoing: what the anchor reaches (how it works).",
    )
    impact.add_argument("--state", action="append", default=None, choices=list(ALL_LANES))
    impact.add_argument("--top", type=int, default=IMPACT_TOP_DEFAULT)
    impact.add_argument("--include-heuristic", action="store_true")
    impact.set_defaults(func=run_impact)

    context = commands.add_parser(
        "context", help="one composed pack for an artifact: parts, usage, permissions, coverage"
    )
    context.add_argument("--identity", required=True)
    context.add_argument("--state", action="append", default=None, choices=list(ALL_LANES))
    context.add_argument("--top", type=int, default=CONTEXT_TOP_DEFAULT)
    context.add_argument("--include-heuristic", action="store_true")
    context.add_argument(
        "--direction", default="incoming", choices=["incoming", "outgoing"],
        help="direction of the `chains` traversal only; the edge sections always report both.",
    )
    context.set_defaults(func=run_context)

    edge_health = commands.add_parser(
        "edge-health", help="how edge targets resolve to entries in this index generation"
    )
    edge_health.set_defaults(func=run_edge_health)

    capabilities = commands.add_parser("capabilities", help="valid facets, operators, modes")
    capabilities.add_argument("--metadata-type", default=None)
    capabilities.set_defaults(func=run_capabilities)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except (SearchError, store.StoreError) as error:
        print(json.dumps({"outcome": "ERROR", "reason": str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
