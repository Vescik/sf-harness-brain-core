#!/usr/bin/env python3
"""Canonical-JSON digest primitives shared by every Knowledge executor.

Relocated verbatim from scripts/knowledge_registry.py (P0 of the v1 claim-registry
retirement, 2026-08-03) so the one-file entry store does not depend on the retiring
module. The byte behavior is load-bearing: canonical_digest() values are persisted as
entry filename suffixes, factsDigest/bodyDigest/reviewedContentDigest, sourceTreeDigest,
org-usage sectionDigest and approval-ledger stamps. Changing the serialization here
silently invalidates every approved Knowledge Entry; tests/test_knowledge_digest.py pins
the exact output.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_digest(value: Any) -> str:
    payload = canonical(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
