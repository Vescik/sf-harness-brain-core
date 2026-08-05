#!/usr/bin/env python3
"""Shared derivations from a raw org observation to a durable, sanitized fact.

One implementation, two consumers. Knowledge's org-usage lane and the Design Case evidence lane
must not each define "field fill" or "cardinality" their own way: two definitions of the same
observed fact is how a design and an entry end up disagreeing about the org while both look
grounded.

Every deriver takes raw rows and returns derived facts only. Raw values leave this module in
exactly one place — `config_snapshot`, the governed exception — and even there only through an
explicit safe-field allowlist. Everything else returns counts, shapes and digests.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence


PERSISTENCE_MODES = ("aggregate", "shape", "config-snapshot", "transient")
DERIVER_VERSION = 1

# Values that must never reach a durable receipt regardless of mode. Salesforce ids are
# excluded because an id is a pointer into live data, not a design fact.
SALESFORCE_ID = re.compile(r"^[a-zA-Z0-9]{15}(?:[a-zA-Z0-9]{3})?$")
SENSITIVE_FIELD = re.compile(
    r"(password|secret|token|credential|ssn|nino|iban|sort_?code|card|cvv|dob|birth)",
    re.IGNORECASE,
)
AUDIT_FIELD = frozenset(
    {"Id", "OwnerId", "CreatedById", "LastModifiedById", "SystemModstamp", "attributes"}
)
MAX_GROUPS = 50
MAX_SAMPLE_PATTERNS = 20


class DeriverError(RuntimeError):
    """A safe, user-actionable derivation failure."""


def _rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise DeriverError("rows must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise DeriverError("each row must be an object")
    return rows


def digest_of(value: Any) -> str:
    import json

    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def value_shape(value: Any) -> str:
    """A structural description that carries no business content."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"object[{len(value)}]"
    text = str(value)
    if SALESFORCE_ID.match(text):
        return "salesforce-id"
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        return "datetime"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return "date"
    if "@" in text and "." in text:
        return "email-like"
    return f"text[{len(text)}]"


# --------------------------------------------------------------------------------------
# Aggregate derivations
# --------------------------------------------------------------------------------------


def object_baseline(rows: Sequence[dict[str, Any]], *, count_field: str = "recordCount") -> dict[str, Any]:
    """Row count and observed date span. Never production volume — a sandbox is not production."""
    rows = _rows(list(rows))
    if len(rows) == 1 and count_field in rows[0]:
        total = int(rows[0][count_field] or 0)
    else:
        total = len(rows)
    dates = []
    for row in rows:
        for key, value in row.items():
            if key in ("CreatedDate", "LastModifiedDate") and isinstance(value, str):
                dates.append(value)
    span = None
    if dates:
        span = {"earliest": min(dates), "latest": max(dates)}
    return {"observedRows": total, "dateSpan": span, "authorityNote": "sandbox observation, not production volume"}


def field_fill(rows: Sequence[dict[str, Any]], fields: Iterable[str]) -> dict[str, Any]:
    """Filled/total per field. Says nothing about whether a filled value is correct."""
    rows = _rows(list(rows))
    total = len(rows)
    result = {}
    for field in fields:
        filled = sum(1 for row in rows if row.get(field) not in (None, "", []))
        result[field] = {"filled": filled, "total": total}
    return {"total": total, "fields": result}


def field_cardinality(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    """Distinct/total. Not index presence and not query-plan selectivity."""
    rows = _rows(list(rows))
    values = [row.get(field) for row in rows if row.get(field) not in (None, "")]
    return {
        "field": field,
        "distinct": len(set(map(str, values))),
        "total": len(values),
        "nullOrEmpty": len(rows) - len(values),
    }


def categorical_distribution(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    """Which status/type/flag values are in use, and how often. Never their business meaning."""
    rows = _rows(list(rows))
    counter = Counter(
        "«null»" if row.get(field) in (None, "") else str(row.get(field))[:120] for row in rows
    )
    groups = [
        {"value": value, "count": count}
        for value, count in counter.most_common(MAX_GROUPS)
    ]
    return {
        "field": field,
        "groups": groups,
        "distinctObserved": len(counter),
        "truncated": len(counter) > MAX_GROUPS,
        "authorityNote": "observed values only; semantics need a human or vendor authority",
    }


def key_integrity(rows: Sequence[dict[str, Any]], key_fields: Sequence[str]) -> dict[str, Any]:
    """Null and duplicate counts for a candidate natural key. Not whether the key is the right one."""
    rows = _rows(list(rows))
    missing = 0
    seen: Counter[str] = Counter()
    for row in rows:
        parts = [row.get(field) for field in key_fields]
        if any(part in (None, "") for part in parts):
            missing += 1
            continue
        seen["␟".join(str(part) for part in parts)] += 1
    duplicates = {key: count for key, count in seen.items() if count > 1}
    return {
        "keyFields": list(key_fields),
        "total": len(rows),
        "missingKey": missing,
        "distinctKeys": len(seen),
        "duplicateGroups": len(duplicates),
        "duplicateRows": sum(duplicates.values()),
    }


def relationship_shape(rows: Sequence[dict[str, Any]], relationship_field: str) -> dict[str, Any]:
    """Fill and fan-out of a relationship. Digest the parent ids; never persist them."""
    rows = _rows(list(rows))
    parents = [row.get(relationship_field) for row in rows if row.get(relationship_field)]
    fan_out = Counter(str(parent) for parent in parents)
    counts = sorted(fan_out.values())
    return {
        "field": relationship_field,
        "filled": len(parents),
        "total": len(rows),
        "distinctParents": len(fan_out),
        "fanOut": {
            "min": counts[0] if counts else 0,
            "max": counts[-1] if counts else 0,
            "median": counts[len(counts) // 2] if counts else 0,
        },
    }


def config_effectivity(
    rows: Sequence[dict[str, Any]],
    *,
    start_field: str,
    end_field: str,
    at: str | None = None,
) -> dict[str, Any]:
    """Active / future / expired buckets and overlap count for effectivity-windowed config."""
    rows = _rows(list(rows))
    moment = at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    buckets = {"active": 0, "future": 0, "expired": 0, "unbounded": 0, "malformed": 0}
    windows: list[tuple[str, str]] = []
    for row in rows:
        start = row.get(start_field)
        end = row.get(end_field)
        if start in (None, "") and end in (None, ""):
            buckets["unbounded"] += 1
            continue
        try:
            low = str(start) if start else "0000-01-01"
            high = str(end) if end else "9999-12-31"
        except (TypeError, ValueError):
            buckets["malformed"] += 1
            continue
        windows.append((low, high))
        if low > moment:
            buckets["future"] += 1
        elif high < moment:
            buckets["expired"] += 1
        else:
            buckets["active"] += 1
    overlaps = 0
    ordered = sorted(windows)
    for index in range(1, len(ordered)):
        if ordered[index][0] <= ordered[index - 1][1]:
            overlaps += 1
    return {
        "evaluatedAt": moment,
        "buckets": buckets,
        "overlappingWindows": overlaps,
        "authorityNote": "window arithmetic only; the intended winner needs source or human evidence",
    }


def sample_shape(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Per-field structural patterns. Deliberately carries no values."""
    rows = _rows(list(rows))
    shapes: dict[str, Counter[str]] = {}
    for row in rows:
        for key, value in row.items():
            if key == "attributes":
                continue
            shapes.setdefault(key, Counter())[value_shape(value)] += 1
    return {
        "observedRows": len(rows),
        "fields": {
            field: [
                {"shape": shape, "count": count}
                for shape, count in counter.most_common(MAX_SAMPLE_PATTERNS)
            ]
            for field, counter in sorted(shapes.items())
        },
        "authorityNote": "structural shapes only; not statistically representative",
    }


# --------------------------------------------------------------------------------------
# Sanitization
# --------------------------------------------------------------------------------------


def safe_config_snapshot(
    rows: Sequence[dict[str, Any]], allowed_fields: Sequence[str]
) -> dict[str, Any]:
    """The one governed exception that persists record values.

    Only explicitly allowlisted scalar fields survive, and even an allowlisted field is dropped
    when it looks like an id, an audit column or sensitive data. A value that cannot be
    persisted safely leaves its digest behind, so the probe stays reproducible without the value.
    """
    rows = _rows(list(rows))
    allowed = [field for field in allowed_fields if field not in AUDIT_FIELD]
    refused = sorted(set(allowed_fields) - set(allowed))
    records = []
    withheld: Counter[str] = Counter()
    for row in rows:
        projected: dict[str, Any] = {}
        for field in allowed:
            value = row.get(field)
            if value is None:
                projected[field] = None
                continue
            if SENSITIVE_FIELD.search(field):
                withheld[field] += 1
                projected[field] = {"withheld": "sensitive-field", "digest": digest_of(value)}
                continue
            if isinstance(value, str) and SALESFORCE_ID.match(value):
                withheld[field] += 1
                projected[field] = {"withheld": "salesforce-id", "digest": digest_of(value)}
                continue
            if isinstance(value, (dict, list)):
                withheld[field] += 1
                projected[field] = {"withheld": "non-scalar", "digest": digest_of(value)}
                continue
            projected[field] = value
        records.append(projected)
    return {
        "records": records,
        "allowedFields": allowed,
        "refusedFields": refused,
        "withheldCounts": dict(withheld),
        "sensitivityClass": "internal-config-snapshot",
    }


DERIVERS = {
    "object-baseline": object_baseline,
    "field-fill": field_fill,
    "field-cardinality": field_cardinality,
    "categorical-distribution": categorical_distribution,
    "key-integrity": key_integrity,
    "relationship-shape": relationship_shape,
    "config-effectivity": config_effectivity,
    "sample-shape": sample_shape,
}


def derive(kind: str, rows: Sequence[dict[str, Any]], **options: Any) -> dict[str, Any]:
    """Dispatch to the named deriver. Unknown kinds fail closed rather than falling back."""
    if kind not in DERIVERS:
        raise DeriverError(
            f"no deriver for probe kind {kind!r}; add one rather than persisting raw rows"
        )
    return DERIVERS[kind](rows, **options)


def transform_policy_digest() -> str:
    """Binds a receipt to the exact derivation contract that produced it."""
    return digest_of(
        {
            "version": DERIVER_VERSION,
            "derivers": sorted(DERIVERS),
            "auditFields": sorted(AUDIT_FIELD),
            "sensitivePattern": SENSITIVE_FIELD.pattern,
            "maxGroups": MAX_GROUPS,
        }
    )
