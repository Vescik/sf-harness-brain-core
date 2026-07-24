"""Target-scale benchmark for the one-file Knowledge store and its search.

The adversarial review required performance to be measured on a named fixture rather than
asserted (review R3-5 / R-20: the validator's `.ai/**` scan and the search build were both
suspected of being over budget by construction at 10-15k entries).

This harness builds a synthetic workspace of N approved entries in a temporary directory —
never in the repository — and reports build time, query latencies, index size, and the cost
of the validator-style reserved-token sweep over the entry corpus.

Synthetic entries are written directly (with real digests and real ledger records) instead of
going through `entry-draft`, because drafting runs the collector per artifact and would measure
extraction, not retrieval. Numbers are only meaningful together with the hardware, the fixture
size, and the runtime version printed in the result.

    python scripts/knowledge_benchmark.py --entries 2000
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import knowledge_search as search  # noqa: E402
from scripts import knowledge_store as store  # noqa: E402
from scripts.force_app_knowledge import file_digest  # noqa: E402
from scripts.validate_harness import reserved_fixture_leaks  # noqa: E402

FLOW_SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Bench Flow {index}</label>
    <processType>AutoLaunchedFlow</processType>
    <status>Active</status>
</Flow>
"""


def synth_workspace(root: Path, entries: int) -> None:
    """Write `entries` approved entries with valid digests and ledger records."""
    flows = root / "force-app/main/default/flows"
    flows.mkdir(parents=True)
    (root / ".ai/knowledge").mkdir(parents=True)
    profile_digest = "sha256:" + "0" * 64
    ledger_lines = []
    for index in range(entries):
        name = f"BenchFlow{index:06d}"
        source_path = flows / f"{name}.flow-meta.xml"
        source_path.write_text(FLOW_SOURCE.format(index=index), encoding="utf-8")
        relative = source_path.relative_to(root).as_posix()
        fragments = [{"path": relative, "sourceDigest": f"sha256:{file_digest(source_path)}"}]
        frontmatter: dict[str, Any] = {
            "schemaVersion": 1,
            "subject": {"metadataType": "Flow", "fullName": name, "namespace": None},
            "profile": {"id": "salesforce.flow", "version": "1.0.0", "digest": profile_digest},
            "scope": {
                "sourceApiVersion": "64.0",
                "sourceTreeDigest": store.canonical_digest(
                    sorted((item["path"], item["sourceDigest"]) for item in fragments)
                ),
                "packageVersionId": None,
            },
            "source": {"fragments": fragments},
            "lifecycle": {"state": "approved", "contentDigest": "sha256:" + "0" * 64},
            "typeFacts": {
                "processType": "AutoLaunchedFlow",
                "status": "Active",
                "trigger": {"object": f"BenchObject{index % 50:03d}__c"},
                "references": [
                    {
                        "kind": "operates-on",
                        "target": f"BenchObject{index % 50:03d}__c",
                        "assurance": "source-exact",
                    }
                ],
            },
            "extractionCoverage": {"typeFacts": "full"},
            "assurance": {"typeFacts": "source-exact"},
            "limitations": [],
            "keywords": [],
            "candidateKeywords": [],
            "sensitivity": "internal-sanitized",
            "approval": {
                "reviewedContentDigest": None,
                "reviewedBy": "Bench Reviewer",
                "reviewedAt": "2026-07-24T00:00:00Z",
                "mechanism": "copilot-chat-entry-confirmation",
            },
        }
        body = f"## Purpose\n\nRoutes bench records for partition {index % 50} to the right queue.\n"
        digest = store.reviewed_content_digest(frontmatter, body)
        frontmatter["approval"]["reviewedContentDigest"] = digest
        frontmatter["lifecycle"]["contentDigest"] = digest
        path = store.entry_path("Flow", None, name)
        store.atomic_write(path, store.render_entry(frontmatter, body))
        ledger_lines.append(
            {
                "sequence": index + 1,
                "action": "approve",
                "identity": store.identity_of("Flow", None, name),
                "reviewedContentDigest": digest,
                "semanticsDigest": store.semantics_digest(body),
                "reviewedBy": "Bench Reviewer",
                "reviewedAt": "2026-07-24T00:00:00Z",
                "mechanism": "copilot-chat-entry-confirmation",
                "chunkId": "bench",
            }
        )
    with store.LEDGER_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for line in ledger_lines:
            handle.write(json.dumps(line, sort_keys=True) + "\n")


def timed(operation: Callable[[], Any], repeats: int) -> dict[str, float]:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return {
        "p50Ms": round(statistics.median(samples), 1),
        "p95Ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 1),
        "maxMs": round(samples[-1], 1),
    }


def run(entries: int, repeats: int) -> dict[str, Any]:
    temporary = Path(tempfile.mkdtemp(prefix="knowledge-bench-")).resolve()
    try:
        with store.rooted(temporary):
            build_started = time.perf_counter()
            synth_workspace(temporary, entries)
            fixture_ms = (time.perf_counter() - build_started) * 1000

            index_started = time.perf_counter()
            built = search.build_index()
            index_ms = (time.perf_counter() - index_started) * 1000

            target = f"Flow:c:BenchFlow{entries // 2:06d}"

            def identity_query() -> None:
                search.run_search(
                    argparse.Namespace(
                        text=None, identity=target, metadata_type=None, namespace=None,
                        state=None, facet=None, relation_anchor=None, relation_kind=None,
                        direction=None, include_heuristic=False, mode="hybrid", top=10,
                    )
                )

            def text_query() -> None:
                search.run_search(
                    argparse.Namespace(
                        text="routes bench records queue", identity=None, metadata_type=None,
                        namespace=None, state=None, facet=None, relation_anchor=None,
                        relation_kind=None, direction=None, include_heuristic=False,
                        mode="hybrid", top=10,
                    )
                )

            def facet_query() -> None:
                search.run_search(
                    argparse.Namespace(
                        text=None, identity=None, metadata_type="Flow", namespace=None,
                        state=None, facet=["flow.trigger.object=BenchObject007__c"],
                        relation_anchor=None, relation_kind=None, direction=None,
                        include_heuristic=False, mode="hybrid", top=10,
                    )
                )

            def relation_query() -> None:
                search.run_search(
                    argparse.Namespace(
                        text=None, identity=None, metadata_type=None, namespace=None,
                        state=None, facet=None, relation_anchor="BenchObject007__c",
                        relation_kind="operates-on", direction=None, include_heuristic=False,
                        mode="hybrid", top=10,
                    )
                )

            def leak_sweep() -> None:
                # Mirrors the validator's runtime-authority sweep over .ai/** (review R3-5).
                for path in (temporary / ".ai").rglob("*"):
                    if path.is_file() and path.stat().st_size <= 1_000_000:
                        reserved_fixture_leaks(path.read_text(encoding="utf-8"))

            measurements = {
                "identityQuery": timed(identity_query, repeats),
                "textQuery": timed(text_query, repeats),
                "facetQuery": timed(facet_query, repeats),
                "relationQuery": timed(relation_query, repeats),
                "validatorLeakSweep": timed(leak_sweep, max(1, repeats // 5)),
            }
            cache = search.cache_root()
            index_bytes = sum(item.stat().st_size for item in cache.rglob("*") if item.is_file())
            entry_bytes = sum(
                item.stat().st_size for item in store.ARTIFACTS_ROOT.rglob("*.md")
            )
            return {
                "fixture": {
                    "entries": entries,
                    "generation": built["generation"],
                    "fixtureBuildMs": round(fixture_ms, 1),
                    "entryBytes": entry_bytes,
                    "indexBytes": index_bytes,
                },
                "environment": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "processor": platform.machine(),
                },
                "indexBuildMs": round(index_ms, 1),
                "queries": measurements,
                "note": (
                    "Synthetic fixture on this machine only. Not a certification for any real "
                    "managed package; Windows numbers must be measured on Windows."
                ),
            }
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge_benchmark", description=__doc__)
    parser.add_argument("--entries", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.entries, args.repeats), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
