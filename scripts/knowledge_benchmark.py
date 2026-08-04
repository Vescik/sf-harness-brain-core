"""Target-scale benchmark for the one-file Knowledge store and its search.

LOCAL TOOL ONLY (owner decision 2026-08-04): CI no longer runs this — the µs/entry budget
gate measured runner noise on a near-empty real corpus. Run it by hand when a performance
question actually comes up; the budget constants below remain the reference numbers.

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

Every BUDGETED measurement is taken in SUBPROCESSES rather than in the warm repeat loop, because
the quantities the plan budgets are per-CLI-process quantities: the freshness floor paid before
any query work, and the latency and peak memory of one command. They were previously read off a
process that had already written the fixture, built the index and run nine other measurements --
so the floor was measured on hot caches and the memory figure covered work no user ever pays for.
The warm loop stays for the query shapes nothing budgets.

    python scripts/knowledge_benchmark.py --entries 2000
    python scripts/knowledge_benchmark.py --entries 3000 --assert-floor-us 5.0 \
        --assert-command-budgets
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

try:  # POSIX-only stdlib.
    import resource
except ModuleNotFoundError:  # pragma: no cover - the windows-latest CI leg takes this branch
    # An unconditional import killed the whole run on windows-latest -- the one platform the
    # plan names as authoritative for the floor budget -- before a single latency sample was
    # taken. The memory instrument is never allowed to be the reason the latency gate cannot run.
    resource = None  # type: ignore[assignment]

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

FIELD_SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Bench{index:06d}__c</fullName>
    <label>Bench {index}</label>
    <type>Text</type>
</CustomField>
"""

# Mix, not Flow-only. A Flow-only corpus contains zero belongs-to edges at any scale, so it
# cannot exercise `parts`, containment traversal, or anything built on them — every budget
# measured on it would be measured on dead code paths.
OBJECT_SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Bench Object {index}</label>
    <sharingModel>ReadWrite</sharingModel>
</CustomObject>
"""

APEX_SOURCE = """public with sharing class BenchHandler{index:06d} {{
    public void run() {{
        BenchHandler{next:06d} next = new BenchHandler{next:06d}();
        next.run();
    }}
}}
"""

# Proportions matter as much as presence. A fixture with fields but no OBJECTS measures `parts`
# on an anchor whose owner has no entry, i.e. an empty answer; one with no Apex chain measures a
# forward traversal that stops at hop 1. Both were being timed and reported as budgets.
PARTITIONS = 50          # distinct owning objects
FIELD_SHARE = 3          # one CustomField per this many non-object entries
APEX_SHARE = 5           # one ApexClass per this many non-object entries

FEATURE_SLUG = "bench-feature"

# Fresh processes per cold probe. See `cold_probe`: below 21 the nearest-rank p95 IS the
# maximum, and a budget asserted against a worst-of-five fails on one noisy sample.
COLD_PROCESSES = 21

# The regimes `search.TRAVERSAL_LIMITS` has to survive, each walked at the depth R7 publishes
# for the command that uses it. Not "a sample of anchors": fanout lives in the hub regime and
# node count in the chain regime, so a single mixed sample would report the maximum of neither.
# `include_heuristic=True` throughout, because the widest walk a caller can ask for is the one
# the limits must bound -- measuring the default filter would certify a ceiling against an
# answer that has already had 82 % of its edges removed (plan R6).
TRAVERSAL_PROBES: tuple[tuple[str, str, str, str], ...] = (
    ("hub", "CustomObject:", "incoming", "tree"),
    ("chain", "ApexClass:", "outgoing", "impact"),
    ("leaf", "CustomField:", "incoming", "context"),
)
TRAVERSAL_PROBE_ANCHORS = 50
# The corpus size the plan budgets (§4.2, §5), and the one this fixture is NOT. Every observed
# number below is measured at BUDGET_ENTRIES and projected here before it is compared to a
# limit: fanout at a fixed object count grows linearly with the corpus, so a limit that merely
# clears the 3 000-entry measurement would start truncating legitimate answers at target scale.
TRAVERSAL_TARGET_ENTRIES = 15000


def synth_workspace(root: Path, entries: int) -> None:
    """Write `entries` approved entries with valid digests and ledger records."""
    flows = root / "force-app/main/default/flows"
    flows.mkdir(parents=True)
    (root / ".ai/knowledge").mkdir(parents=True)
    profile_digest = "sha256:" + "0" * 64
    ledger_lines = []
    for index in range(entries):
        owner = f"BenchObject{index % PARTITIONS:03d}__c"
        is_object = index < PARTITIONS
        is_apex = not is_object and index % APEX_SHARE == 0
        is_field = not is_object and not is_apex and index % FIELD_SHARE == 0
        if is_object:
            metadata_type = "CustomObject"
            name = f"BenchObject{index:03d}__c"
            objects_dir = root / f"force-app/main/default/objects/{name}"
            objects_dir.mkdir(parents=True, exist_ok=True)
            source_path = objects_dir / f"{name}.object-meta.xml"
            source_path.write_text(OBJECT_SOURCE.format(index=index), encoding="utf-8")
        elif is_apex:
            metadata_type = "ApexClass"
            name = f"BenchHandler{index:06d}"
            classes_dir = root / "force-app/main/default/classes"
            classes_dir.mkdir(parents=True, exist_ok=True)
            source_path = classes_dir / f"{name}.cls"
            source_path.write_text(
                APEX_SOURCE.format(index=index, next=index + APEX_SHARE), encoding="utf-8"
            )
        elif is_field:
            metadata_type = "CustomField"
            name = f"{owner}.Bench{index:06d}__c"
            fields_dir = root / f"force-app/main/default/objects/{owner}/fields"
            fields_dir.mkdir(parents=True, exist_ok=True)
            source_path = fields_dir / f"Bench{index:06d}__c.field-meta.xml"
            source_path.write_text(FIELD_SOURCE.format(index=index), encoding="utf-8")
        else:
            metadata_type = "Flow"
            name = f"BenchFlow{index:06d}"
            source_path = flows / f"{name}.flow-meta.xml"
            source_path.write_text(FLOW_SOURCE.format(index=index), encoding="utf-8")
        relative = source_path.relative_to(root).as_posix()
        fragments = [{"path": relative, "sourceDigest": f"sha256:{file_digest(source_path)}"}]
        profile = {
            "CustomObject": {"id": "salesforce.custom-object", "version": "1.0.0", "digest": profile_digest},
            "CustomField": {"id": "salesforce.custom-field", "version": "1.0.0", "digest": profile_digest},
            "ApexClass": {"id": "salesforce.apex", "version": "1.0.0", "digest": profile_digest},
            "Flow": {"id": "salesforce.flow", "version": "1.0.0", "digest": profile_digest},
        }[metadata_type]
        frontmatter: dict[str, Any] = {
            "schemaVersion": 1,
            "subject": {"metadataType": metadata_type, "fullName": name, "namespace": None},
            "profile": profile,
            "scope": {
                "sourceApiVersion": "64.0",
                "sourceTreeDigest": store.canonical_digest(
                    sorted((item["path"], item["sourceDigest"]) for item in fragments)
                ),
                "packageVersionId": None,
                # Synthetic corpus, not collector output — 0.0.0 keeps that visible.
                "collectorVersion": "0.0.0",
            },
            "source": {"fragments": fragments},
            "lifecycle": {"state": "approved", "contentDigest": "sha256:" + "0" * 64},
            "typeFacts": {
                "CustomObject": {"objectKind": "custom", "sharingModel": "ReadWrite"},
                "CustomField": {
                    "object": owner, "type": "Text",
                    "references": [{"kind": "belongs-to", "target": owner, "assurance": "source-exact"}],
                },
                "ApexClass": {
                    "kind": "ApexClass", "sharingModel": "with",
                    "references": [
                        # A real chain: each handler constructs the next, so a forward traversal
                        # actually reaches hop 2 and beyond instead of stopping immediately.
                        {"kind": "invokes-class", "target": f"BenchHandler{index + APEX_SHARE:06d}",
                         "assurance": "source-derived-heuristic"},
                        {"kind": "object-token", "target": owner,
                         "assurance": "source-derived-heuristic"},
                    ],
                },
                "Flow": {
                    "processType": "AutoLaunchedFlow", "status": "Active",
                    "trigger": {"object": owner},
                    "references": [{"kind": "operates-on", "target": owner, "assurance": "source-exact"}],
                },
            }[metadata_type],
            "extractionCoverage": {"typeFacts": "full"},
            "assurance": {
                "typeFacts": "source-derived-heuristic" if metadata_type == "ApexClass" else "source-exact"
            },
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
        path = store.entry_path(metadata_type, None, name)
        store.atomic_write(path, store.render_entry(frontmatter, body))
        ledger_lines.append(
            {
                "sequence": index + 1,
                "action": "approve",
                "identity": store.identity_of(metadata_type, None, name),
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


def synth_feature(root: Path, anchor: str) -> str:
    """Approve one Feature Entry anchored on `anchor`, so `tree` and `feature-drift` have a rule.

    Both commands were entirely unmeasured: the benchmark never called them, so §6's "each state
    an absolute p95 and peakRssMb" had no instrument at all -- not a platform limitation, an
    absent measurement. They cannot be measured on entries alone, because a feature is the one
    thing in this store a human authors rather than the collector emitting it.

    This goes through the real propose/describe/approve path rather than writing the file
    directly (as the entries are): the approval is what pins the `membershipDigest` the ledger
    carries, and `feature-drift` answers `changed` from that pin. A hand-written file would
    measure the "unknown, nothing to compare" branch, which is the cheap one.
    """

    config = root / "config/harness.local.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps({"knowledge": {"chatReviewer": "Bench Reviewer"}}), encoding="utf-8"
    )
    store.command_feature_propose(
        argparse.Namespace(
            slug=FEATURE_SLUG, name="Bench Feature", anchor=[anchor], hub=None, depth=1,
            include=None, exclude=None, assurance_floor="source-exact", replace=True,
        )
    )
    purpose = root / "bench-feature-purpose.md"
    purpose.write_text(
        f"Everything that composes {anchor} and the automation that operates on it.\n",
        encoding="utf-8",
    )
    store.command_feature_describe(
        argparse.Namespace(slug=FEATURE_SLUG, purpose_file=str(purpose))
    )
    review = store.command_feature_review(argparse.Namespace(slug=[FEATURE_SLUG]))
    pins = [part for part in review["approveCommand"].split() if part.startswith("Feature:")]
    store.command_feature_approve(argparse.Namespace(feature=pins))
    return FEATURE_SLUG


def peak_rss_mb() -> tuple[float | None, str]:
    """Peak resident set of THIS process in MB, plus the name of the instrument that produced it.

    Returns `(None, reason)` instead of raising. The Unix-only `resource` module is not a
    reason to have no number at all, and it is certainly not a reason for the latency gate to
    die: a missing memory instrument degrades to an explicit null with a stated cause, which a
    reader can tell apart from "0 MB".
    """
    if resource is not None:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is bytes on macOS and kilobytes on Linux -- the same field, two units.
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(usage / divisor, 1), "resource.getrusage(RUSAGE_SELF).ru_maxrss"
    if sys.platform == "win32":
        # Windows has no `resource`, but PeakWorkingSetSize is the same quantity and ctypes is
        # stdlib, so the team's own platform still gets a measured number rather than a null.
        #
        # WHAT IS PROVEN AND WHAT IS NOT. This branch is exercised on every platform by
        # `test_the_windows_peak_rss_path_is_executed_not_merely_written`, which doubles
        # `ctypes.WinDLL` and runs the real structure definition, the real signature
        # declarations, the real `sizeof` and the real byte->MB arithmetic. What that test
        # cannot prove is the kernel side: that `K32GetProcessMemoryInfo` is exported from
        # kernel32 on the runner's Windows build and returns a plausible working set. Until a
        # windows-latest run reports `peakRssSource` naming this instrument, every peakRssMb
        # ceiling in TRAVERSAL_BUDGETS is verified on macOS/Linux only -- the numbers are
        # measured, the PLATFORM the plan names as authoritative is not.
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # Signatures are declared, not defaulted: HANDLE is 64-bit on x64 and ctypes would
            # otherwise pass the pseudo-handle as a 32-bit int.
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.K32GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD
            ]
            kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            ok = kernel32.K32GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            )
            if not ok:
                return None, f"K32GetProcessMemoryInfo failed (error {ctypes.get_last_error()})"
            return round(counters.PeakWorkingSetSize / (1024 * 1024), 1), (
                "kernel32.K32GetProcessMemoryInfo PeakWorkingSetSize"
            )
        except (OSError, AttributeError) as error:
            return None, f"windows peak-RSS instrument unavailable: {error}"
    return None, f"no peak-RSS instrument available on {sys.platform}"


def p95(sorted_samples: list[float]) -> float:
    """Nearest-rank 95th percentile: the smallest sample at or above 95% of the population.

    `int(n * 0.95)` returned the MAXIMUM for every n <= 20 -- so the shipped floor gate, run
    with five cold processes, was asserting a worst-of-five against a budget calibrated on a
    median. One slow sample on a shared CI runner failed the build, which is how a budget
    teaches people to press re-run. Nearest rank keeps the same value where n is large and
    stops calling a maximum a percentile where n is small.
    """
    if not sorted_samples:
        raise ValueError("no samples")
    rank = max(1, math.ceil(0.95 * len(sorted_samples)))
    return sorted_samples[min(rank - 1, len(sorted_samples) - 1)]


def timed(operation: Callable[[], Any], repeats: int) -> dict[str, float]:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return {
        "p50Ms": round(statistics.median(samples), 1),
        "p95Ms": round(p95(samples), 1),
        "maxMs": round(samples[-1], 1),
    }


def traversal_observations(
    documents: Any, available: list[str], allowed: set[str], entries: int
) -> dict[str, Any]:
    """What a walk actually reaches on the mixed corpus, per regime.

    §9's last open item: `TRAVERSAL_LIMITS` were chosen constants -- the audit's own word -- with
    nothing behind them and no clock among them at all, so a walk whose nodes are individually
    expensive could only ever terminate on a node count it might never reach. These are the
    numbers the limits are now set from.

    Read off `search.traverse` itself rather than a reimplementation of the walk: a table derived
    from a second BFS would certify limits against code nobody runs, which is the failure the
    shared `traverse` was extracted to prevent in the first place.
    """

    regimes: dict[str, Any] = {}
    for name, prefix, direction, command in TRAVERSAL_PROBES:
        depth = search.DEPTH_LIMITS[command]
        anchors = [item for item in available if item.startswith(prefix)][:TRAVERSAL_PROBE_ANCHORS]
        fanouts: list[float] = []
        nodes: list[float] = []
        elapsed: list[float] = []
        for identity in anchors:
            started = time.perf_counter()
            walk = search.traverse(
                documents, identity, depth=depth, direction=direction,
                allowed=allowed, include_heuristic=True,
            )
            elapsed.append((time.perf_counter() - started) * 1000)
            fanouts.append(walk["observed"]["maxFanout"])
            nodes.append(walk["observed"]["nodes"])
        if not anchors:
            continue
        fanouts.sort()
        nodes.sort()
        elapsed.sort()
        scale = TRAVERSAL_TARGET_ENTRIES / max(entries, 1)
        regimes[name] = {
            "anchors": len(anchors),
            "anchorPrefix": prefix,
            "direction": direction,
            "depth": depth,
            "depthFrom": f"DEPTH_LIMITS[{command!r}] (R7: semantic, never benchmark-derived)",
            "maxFanout": int(fanouts[-1]),
            "p95Fanout": int(p95(fanouts)),
            "maxNodes": int(nodes[-1]),
            "p95Nodes": int(p95(nodes)),
            "maxWalkMs": round(elapsed[-1], 2),
            "p95WalkMs": round(p95(elapsed), 2),
            # Linear projection to the corpus size the plan budgets. Fanout at a fixed object
            # count and node count both scale with the number of entries pointing at an anchor,
            # so this is the quantity a limit has to clear -- not the 3 000-entry measurement.
            "projectedMaxFanoutAt15k": int(fanouts[-1] * scale),
            "projectedMaxNodesAt15k": int(nodes[-1] * scale),
            "projectedMaxWalkMsAt15k": round(elapsed[-1] * scale, 2),
        }
    return {
        "entries": entries,
        "targetEntries": TRAVERSAL_TARGET_ENTRIES,
        "includeHeuristic": True,
        "configured": dict(search.TRAVERSAL_LIMITS),
        "regimes": regimes,
    }


def probe_call(probe: str, target: str | None) -> Callable[[], Any]:
    """The one command a cold probe process runs, argument-for-argument as the CLI would.

    Namespaces are spelled out rather than defaulted through `getattr`: a benchmark that omits
    a flag measures a different code path from the one the parser produces, and `--top` is
    exactly such a flag -- omitting it timed `explain` against its fallback instead of against
    EXPLAIN_TOP_DEFAULT, which is what a user gets.
    """

    calls: dict[str, Callable[[], Any]] = {
        "fingerprint": lambda: search.corpus_fingerprint(),
        "explain": lambda: search.run_explain(
            argparse.Namespace(
                identity=target, state=None, top=search.EXPLAIN_TOP_DEFAULT,
                include_heuristic=True,
            )
        ),
        "impact": lambda: search.run_impact(
            argparse.Namespace(
                identity=target, depth=search.DEPTH_LIMITS["impact"], direction="outgoing",
                state=None, top=50, include_heuristic=True,
            )
        ),
        "context": lambda: search.run_context(
            argparse.Namespace(
                identity=target, state=None, top=25, include_heuristic=True, direction="incoming",
            )
        ),
        "tree": lambda: search.run_tree(
            argparse.Namespace(
                feature=target, state=None, include_heuristic=False, direction="incoming",
            )
        ),
        "drift": lambda: search.run_feature_drift(
            argparse.Namespace(feature=target, state=None, include_heuristic=False)
        ),
    }
    return calls[probe]


def cold_probe_child(root: Path, probe: str, target: str | None) -> int:
    """One measurement of the FIRST call in a FRESH interpreter, printed as JSON.

    Re-entered as a subprocess by `cold_probe`. Everything a CLI invocation pays on its way to
    an answer is inside the timed region -- including `code_fingerprint()`, which hashes four
    module files on its first call and is memoised for the rest of the process, so a warm loop
    never pays it again.
    """
    # Baseline AFTER imports, BEFORE the command. The process total is dominated by the
    # interpreter and this module's import graph (yaml, jsonschema, the 6.6k-line collector),
    # which every probe pays identically -- ubuntu-latest reported the same 106.3 MB for the
    # floor sweep and all five traversals, a figure in which no command-level regression could
    # ever be visible. R4 budgets "the latency and peak memory of ONE COMMAND", so the budgeted
    # quantity is what the command ADDS. The total is still reported, clearly scoped and
    # deliberately unbudgeted, because it is the honest answer to "what does a CLI call cost".
    baseline, _ = peak_rss_mb()
    with store.rooted(root):
        started = time.perf_counter()
        probe_call(probe, target)()
        elapsed_us = (time.perf_counter() - started) * 1_000_000
    peak, source = peak_rss_mb()
    # A high-water mark cannot go down, so the delta is a LOWER bound on the command's own peak
    # whenever imports already peaked higher. That direction is the safe one: it under-reports
    # the command rather than blaming it for the interpreter.
    command_rss = None if peak is None or baseline is None else round(max(0.0, peak - baseline), 1)
    print(json.dumps({
        "elapsedUs": elapsed_us,
        "peakRssMb": peak,
        "commandRssMb": command_rss,
        "peakRssSource": source,
    }))
    return 0


def cold_probe(root: Path, probe: str, identity: str | None, processes: int) -> dict[str, Any]:
    """Run `processes` fresh interpreters and summarise their first-call cost and peak RSS.

    The budgeted quantity is the COLD per-CLI-process cost -- "stats every entry file on EVERY
    invocation ... before any query work". A warm in-process repeat loop measures a path no CLI
    invocation ever takes: the interpreter is hot, the module caches are populated, and the OS
    has just walked the same directories nine times for the other measurements. Cold is also
    the only honest place to read peak RSS: a fresh process's peak is the command's own, not
    the benchmark's fixture writing and index build.

    `processes` is 21 by default and that number is load-bearing, not a round figure: the
    nearest-rank 95th percentile of fewer than 21 samples IS the maximum, so the five-process
    default this shipped with was asserting a worst-of-five. Measured on the floor sweep, the
    same statistic moved 2.69-5.72 us/entry across eight runs at five processes and 2.82-3.82
    across six runs at twenty-one -- the budget got a real percentile and the build stopped
    depending on one scheduling hiccup.
    """
    samples: list[float] = []
    peaks: list[float] = []
    command_peaks: list[float] = []
    sources: set[str] = set()
    command = [sys.executable, str(Path(__file__).resolve()), "--cold-probe", probe,
               "--cold-probe-root", str(root)]
    if identity:
        command += ["--cold-probe-identity", identity]
    for _ in range(processes):
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"cold probe '{probe}' failed: {completed.stderr.strip()}")
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        samples.append(payload["elapsedUs"])
        sources.add(payload["peakRssSource"])
        if payload["peakRssMb"] is not None:
            peaks.append(payload["peakRssMb"])
        if payload.get("commandRssMb") is not None:
            command_peaks.append(payload["commandRssMb"])
    samples.sort()
    peaks.sort()
    return {
        "processes": processes,
        "freshProcessPerSample": True,
        "p50Us": round(statistics.median(samples), 1),
        "p95Us": round(p95(samples), 1),
        "minUs": round(samples[0], 1),
        "p95Ms": round(p95(samples) / 1000, 1),
        "commandRssMb": round(max(command_peaks), 1) if command_peaks else None,
        "peakRssMb": round(max(peaks), 1) if peaks else None,
        "peakRssSource": "; ".join(sorted(sources)),
        "commandRssScope": f"peak RSS the '{probe}' call ADDS over the post-import baseline (budgeted)",
        "peakRssScope": (
            f"one fresh '{probe}' process: interpreter, imports and the command itself "
            "(reported, NOT budgeted -- import cost dominates it and is identical for every probe)"
        ),
    }


def run(entries: int, repeats: int, cold_processes: int = COLD_PROCESSES) -> dict[str, Any]:
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
                        text="partition 7 queue", identity=None, metadata_type=None,
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

            def load_index_call() -> None:
                # The floor every command pays before any query work: freshness check + index open.
                search.load_index()

            def corpus_fingerprint_call() -> None:
                search.corpus_fingerprint()

            # Anchors are DISCOVERED, not computed. A formula that assumed the type mix silently
            # produced an identity no fixture size actually contains, and the traversal it was
            # meant to time then measured a raised exception or an empty answer.
            store_documents, _manifest = search.load_index()
            available = store_documents.identities()

            def first_of(prefix: str) -> str | None:
                return next((item for item in available if item.startswith(prefix)), None)

            def first_with_parts(prefix: str) -> str | None:
                """First identity of `prefix` whose inverted containment set is NON-EMPTY.

                Discovering the type was not enough. `identities()` is sorted, so
                `first_of("CustomObject:")` is deterministically partition 0 -- and
                `index % PARTITIONS == 0` implies `index % APEX_SHARE == 0`, so partition 0
                holds only ApexClass and owns no field. The two measurements added
                *specifically* so composition would not be timed against an empty answer were
                therefore both timing `parts: []`. Ask for the answer, never assume the mix.
                """
                for identity in available:
                    if not identity.startswith(prefix):
                        continue
                    document = store_documents.get(identity)
                    name = document["facets"].get("fullName") or identity
                    if store_documents.incoming_edges(
                        name, kinds={search.CONTAINMENT_KIND}, include_heuristic=True
                    ):
                        return identity
                return None

            object_identity = first_of("CustomObject:")
            apex_identity = first_of("ApexClass:")
            # Prefer an object that actually owns parts (that is the inverted containment path
            # under measurement); fall back so tiny fixtures still run rather than crashing.
            parts_identity = first_with_parts("CustomObject:") or object_identity or available[0]
            chain_identity = apex_identity or parts_identity

            # The anchor object of the feature rule: the one whose composition is non-empty, so
            # `tree` walks real members rather than certifying a budget against an empty answer.
            anchor_name = (
                store_documents.get(parts_identity)["facets"].get("fullName") or parts_identity
            )
            feature_slug = synth_feature(temporary, str(anchor_name))

            def leak_sweep() -> None:
                # Mirrors the validator's runtime-authority sweep over .ai/** (review R3-5).
                for path in (temporary / ".ai").rglob("*"):
                    if path.is_file() and path.stat().st_size <= 1_000_000:
                        reserved_fixture_leaks(path.read_text(encoding="utf-8"))

            # The warm loop keeps the query shapes it always had; the traversals moved to the
            # cold probes below, because a traversal's budget is a per-CLI-process quantity and
            # a warm repeat measures a path no invocation takes.
            measurements = {
                "identityQuery": timed(identity_query, repeats),
                "textQuery": timed(text_query, repeats),
                "facetQuery": timed(facet_query, repeats),
                "relationQuery": timed(relation_query, repeats),
                "loadIndex": timed(load_index_call, repeats),
                "corpusFingerprint": timed(corpus_fingerprint_call, repeats),
                "validatorLeakSweep": timed(leak_sweep, max(1, repeats // 5)),
            }

            # What the budgeted anchors actually answered. A composition measurement against an
            # empty `parts` array is a measurement of nothing, and nothing in the emitted result
            # said so -- so it stayed wrong through every run the project made.
            explained = search.run_explain(
                argparse.Namespace(
                    identity=parts_identity, state=None, top=search.EXPLAIN_TOP_DEFAULT,
                    include_heuristic=True,
                )
            )
            contexted = search.run_context(
                argparse.Namespace(
                    identity=parts_identity, state=None, top=25, include_heuristic=True,
                    direction="incoming",
                )
            )
            impacted = search.run_impact(
                argparse.Namespace(
                    identity=chain_identity, depth=search.DEPTH_LIMITS["impact"],
                    direction="outgoing", state=None, top=50, include_heuristic=True,
                )
            )
            treed = search.run_tree(
                argparse.Namespace(
                    feature=feature_slug, state=None, include_heuristic=False,
                    direction="incoming",
                )
            )
            # Bytes, not just milliseconds. `postingBytesRead` is query-INDEPENDENT — reverse,
            # offsets and lanes are read whole on every relation query — and it grows linearly
            # with the corpus, so it is the term that decides how the latency and memory
            # budgets above will age. It is also the only budgeted quantity here that is
            # deterministic rather than sampled, so it fails on a real regression and never on
            # a noisy runner. `tree`/`feature-drift` read the same families through the same
            # DocumentStore but do not emit the counter, so they are not separately budgeted.
            posting_bytes_read = {
                name: result["counts"]["postingBytesRead"]
                for name, result in (
                    ("explain", explained), ("impact", impacted), ("context", contexted)
                )
            }
            corpus_mix: dict[str, int] = {}
            for identity in available:
                metadata_type = identity.split(":", 1)[0]
                corpus_mix[metadata_type] = corpus_mix.get(metadata_type, 0) + 1

            # Warm and in-process on purpose, unlike everything budgeted below: these are not
            # latencies a user waits for, they are the SHAPE of the graph -- how wide a frontier
            # gets and how many nodes a walk reaches. Process startup would add a constant to
            # every sample and change none of them.
            traversal_observed = traversal_observations(
                store_documents, available, store_documents.lane_ids(["approved-current"]), entries
            )

            # Cold, in fresh processes: the floor every CLI invocation pays before any query
            # work, and the peak RSS of a real single-command process. Both are the quantities
            # the plan budgets; both were previously read off a warm loop inside a process that
            # had already written the fixture and built the index.
            cold_floor = cold_probe(temporary, "fingerprint", None, cold_processes)
            # Every traversal the plan budgets, each in its own fresh process. The `tree` call
            # above has already written the membership baseline, which matters: without it
            # `drift` measures its cheap "no cache here, detail withheld" branch instead of the
            # one that actually diffs the member list and names what moved.
            probe_targets = {
                "explain": parts_identity, "impact": chain_identity, "context": parts_identity,
                "tree": feature_slug, "drift": feature_slug,
            }
            cold_commands = {
                name: cold_probe(temporary, name, probe_targets[name], cold_processes)
                for name in COMMAND_BUDGETS
            }
            cold_context = cold_commands["context"]

            # Decomposed, because a cold call is not all per-entry work: `code_fingerprint()`
            # hashes four module files on its first call in every process, and that fixed cost
            # (~0.2 ms here) is charged to whatever entry count the run used. Dividing the cold
            # call by `entries` therefore reports a per-entry cost that FALLS as the fixture
            # grows -- the "run it smaller" escape, inverted. The empty-root probe measures the
            # fixed term directly so the budgeted number is the marginal per-entry sweep.
            empty_root = Path(tempfile.mkdtemp(prefix="knowledge-bench-empty-")).resolve()
            try:
                cold_fixed = cold_probe(empty_root, "fingerprint", None, cold_processes)
            finally:
                shutil.rmtree(empty_root, ignore_errors=True)
            # p95 for the corpus sweep, MEDIAN for the fixed term being subtracted: taking p95 on
            # both sides would let a slow fixed sample cancel a slow sweep sample and understate
            # the marginal cost. This pairing errs toward failing the gate, which is the only
            # safe direction for a budget.
            fixed_us = cold_fixed["p50Us"]
            marginal_us = max(0.0, cold_floor["p95Us"] - fixed_us) / max(entries, 1)
            cold_floor["fixedUs"] = fixed_us
            cold_floor["perEntryUs"] = round(marginal_us, 2)
            cold_floor["projectedMsAt15k"] = round((fixed_us + marginal_us * 15000) / 1000, 1)
            # The ASSERTED number, and the p95 above is the reported one. That is the opposite
            # of what shipped, and it is what the measurements forced: on this machine the same
            # fixture and the same code gave a p95 of 8.3 ms and of 34.0 ms depending only on
            # what else was running, while the minimum moved 7.4 -> 11.4 ms across the same
            # spread. A p95 over 21 cold processes is a measurement of the RUNNER'S tail; the
            # minimum is the noise-floor estimate of the code, it is what a regression has to
            # move, and it is the standard estimator for a microbenchmark for exactly this
            # reason. Both are emitted, so a red gate can always be read as one or the other.
            from_min = max(0.0, cold_floor["minUs"] - fixed_us) / max(entries, 1)
            cold_floor["perEntryUsFromMin"] = round(from_min, 2)
            cold_floor["projectedMsAt15kFromMin"] = round((fixed_us + from_min * 15000) / 1000, 1)

            # The whole-process figure is kept, but it is NOT a command's memory cost: it covers
            # fixture writing and the index build too. Read coldContext.peakRssMb for the number
            # a single CLI invocation actually pays.
            process_peak, process_peak_source = peak_rss_mb()
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
                    "peakRssMb": process_peak,
                    "peakRssSource": process_peak_source,
                    "peakRssScope": (
                        "whole benchmark process: fixture writing, index build and every "
                        "measurement -- an upper bound, not a per-command cost"
                    ),
                    "indexBytes": index_bytes,
                    "corpusMix": corpus_mix,
                },
                "anchors": {
                    "partsIdentity": parts_identity,
                    "chainIdentity": chain_identity,
                    "featureSlug": feature_slug,
                    "explainParts": len(explained["parts"]),
                    "contextParts": len(contexted["parts"]),
                    # A tree over an unapproved rule or an empty membership would certify the
                    # `tree`/`drift` budgets against an answer nobody could get in production.
                    "featureLane": treed["featureLane"],
                    "treeMembers": len(treed["members"]),
                },
                "environment": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "processor": platform.machine(),
                },
                "indexBuildMs": round(index_ms, 1),
                "queries": measurements,
                "coldFloor": cold_floor,
                "coldContext": cold_context,
                "coldCommands": cold_commands,
                "traversalObserved": traversal_observed,
                "postingBytesReadPerQuery": posting_bytes_read,
                "note": (
                    "Synthetic fixture on this machine only. Not a certification for any real "
                    "managed package; Windows numbers must be measured on Windows."
                ),
            }
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


# --- the traversal budgets (R4) -----------------------------------------------------------
#
# R4: "every phase that adds a traversal states an ABSOLUTE latency and memory budget measured
# by knowledge_benchmark.py". Three of the five traversals had no budget of any kind and none
# had a memory budget, so this table is the single place the numbers live -- not the workflow
# file, where a ceiling drifts away from the measurement that justified it.
#
# The five the plan names are FLOOR/impact/context/tree/drift (PLAN_TRAVERSALS, below). The
# per-command rows here cover four of them plus `explain`; the floor's memory ceiling is
# FLOOR_BUDGET, because the floor is not a command.
#
# Every row is stated AT `BUDGET_ENTRIES` and the gate refuses to run at any other fixture size.
# A budget met by running the benchmark smaller is the escape this project has already closed
# once, on the floor gate; a table of absolute milliseconds is wide open to it.
#
# HOW THE NUMBERS WERE CHOSEN. Each ceiling comes from real cold measurements on this machine
# (macOS 15 / APFS, Apple silicon, Python 3.12, the 3000-entry mixed fixture above, 21 fresh
# processes per command, 11 runs spread across machine loads of 4-10 on 10 cores) with a stated
# allowance on top. NOTHING here is inflated to make a measurement pass. Each command is
# budgeted TWICE, because the two statistics answer different questions and only one of them is
# stable (`--assert-floor-us` documents the same finding at length):
#
#   command   measured min (11 runs)  minMs   measured p95 (11 runs)  p95Ms   peak RSS  budget
#   explain      14.3 -  28.9 ms       60      16.8 -  79.2 ms        200    31-33 MB   96 MB
#   impact       20.1 -  34.2 ms       70      21.5 -  69.5 ms        200    31-33 MB   96 MB
#   context      93.0 - 145.9 ms      300     108.4 - 256.4 ms        500    31-33 MB   96 MB
#   tree         15.6 -  21.5 ms       60      17.7 - 119.0 ms        250    31-33 MB   96 MB
#   drift        15.2 -  21.2 ms       60      17.2 -  34.1 ms        250    31-33 MB   96 MB
#
# `minMs` is the noise floor of 21 cold processes and it is the regression detector: it moved
# 2x across every run above while the p95 of the same samples moved 4.7x, and no regression can
# make a minimum faster. `p95Ms` is the plan's own statistic (§5, §6) and is kept, budgeted
# generously, because it is the number that describes what a user waits for -- but a ceiling
# tight enough to catch a regression there would fail on a busy runner instead.
#
# Both allowances are ~2-3x the worst sample measured. That is a platform allowance, not
# padding: the plan names `windows-latest` as authoritative, NTFS + Defender make every file of
# this fixture cost more than APFS does, and GitHub's shared runners add scheduling noise on
# top. It is still a budget with teeth -- every one of these commands is dominated by
# `load_index()`, so a regression that reloaded the index per section, or dropped the
# posting-family laziness, or hydrated before capping, lands well past 3x. The memory allowance
# is 3x on a far steadier quantity: peak RSS moved by under 2 MB across every run taken here,
# and 96 MB is roughly what a command that materialised the whole corpus instead of its capped
# sections would reach.
#
# `postingBytesRead` is the exception: it is DETERMINISTIC (the posting families are read whole
# and identically for every relation query -- 785 459 bytes at 3000 entries for all three of
# explain/impact/context), so its ceiling sits just above the measurement rather than 3x above
# it. It is also the term that decides how the other two age: it is the only quantity here that
# grows linearly with the corpus, and nothing budgeted it before.
#
# THE DEVIATION, STATED. §5 words its budget as "context --identity p95 <= 400 ms ... at 15 k on
# windows-latest" and §6 the same shape for tree/drift. These ceilings are at 3 000 entries, not
# 15 k, because a 15 k fixture costs ~25 s to write and ~2 min to index per CI leg and a gate
# that slow gets deleted. So: `context` is budgeted at 500 ms at 3 000 -- LOOSER than the plan's
# number at a fifth of the corpus -- and that is a deviation, not compliance. It is set where it
# is because the enforceable statistic was measured at 182.7-256.4 ms on a loaded developer
# machine and the authoritative platform is slower still. The honest 15 k figure is unmeasured
# on windows-latest by anyone; the first green runs of this gate are what should tighten it.
BUDGET_ENTRIES = 3000

COMMAND_BUDGETS: dict[str, dict[str, float]] = {
    "explain": {"minMs": 60.0, "p95Ms": 200.0, "commandRssMb": 20.0, "postingBytesRead": 1_000_000},
    "impact": {"minMs": 70.0, "p95Ms": 200.0, "commandRssMb": 20.0, "postingBytesRead": 1_000_000},
    "context": {"minMs": 300.0, "p95Ms": 500.0, "commandRssMb": 20.0, "postingBytesRead": 1_000_000},
    "tree": {"minMs": 60.0, "p95Ms": 250.0, "commandRssMb": 20.0},
    "drift": {"minMs": 60.0, "p95Ms": 250.0, "commandRssMb": 20.0},
}

# THE FIFTH TRAVERSAL. §4.2's P2 gate reads "freshness floor p95 <= 40 ms at 15 k on
# windows-latest; `peakRssMb` BUDGETED, not merely measured" -- and merely measured is exactly
# what it was: `coldFloor` memory was computed, printed and asserted by nothing, because the
# memory half of the gate was folded into a per-command table with no row for the floor. The
# floor is not a command, it is the sweep every command pays before any query work, so it gets
# its own row rather than a synthetic entry in COMMAND_BUDGETS.
#
# WHAT THESE CEILINGS MEASURE, AND WHY THEY MOVED. They were process-total peak RSS, and
# ubuntu-latest reported the SAME 106.3 MB for the floor sweep and all five traversals -- a
# figure in which no command-level regression could ever be visible, because it is dominated by
# the interpreter and this module's import graph, which every probe pays identically. The
# ceilings were also derived on macOS (27-33 MB), so the first Linux run failed six budgets at
# once without a single command having regressed. Both problems have one cause and one fix: the
# budgeted quantity is now what the command ADDS over its own post-import baseline, which is a
# property of the code rather than of the platform's interpreter and allocator.
#
# Measured that way (macOS 15, Apple silicon, 3000-entry mixed fixture, 21 fresh processes per
# probe): floor 0.1 MB; impact 4.7; explain 5.6; tree 5.6; context 5.7; drift 5.7. The commands
# cost what loading the index costs; the floor costs nothing, because it stats and does not
# load. So 20 MB for a command (~3.5x the worst) and 4 MB for the floor.
#
# The floor's 4 MB is not slack, it is the discriminator: the regression this row exists to
# catch is a floor that stops being a stat sweep and starts materialising the corpus it stats,
# and that lands at ~5 MB the moment it loads the index -- over the ceiling at 3000 entries and
# further over at every larger corpus. A ceiling set from the process total could not see that
# at all.
#
# The process total is still reported per probe, as `processRssMb` with its scope spelled out,
# and is deliberately NOT budgeted: it is the honest answer to "what does one CLI call cost"
# and a useless answer to "did this command regress".
#
# The LATENCY half of the floor's budget is `--assert-floor-us`, deliberately a per-entry rate
# rather than an absolute millisecond ceiling: the floor is the one budgeted quantity that grows
# with the corpus, so an absolute number could be met by running the benchmark smaller. The
# workflow states the rate, its derivation from §4.2's 40 ms at 15 k, and the deviation.
FLOOR_BUDGET: dict[str, float] = {"commandRssMb": 4.0}

# R4's matrix, over the PLAN's five traversals rather than over whichever rows this file happens
# to contain. Each value cites the clause that demands the budget, so a reader can check the set
# against the plan instead of against this table -- "a gate that counts its own list can be green
# and mean nothing" is how the floor's missing memory ceiling survived a wave of remediation that
# reported 5 of 5. `explain` is budgeted too and is deliberately NOT in this set: it is a row
# beyond what the plan requires, and the tests check the set is covered, never that it is exact.
PLAN_TRAVERSALS: dict[str, str] = {
    "floor": "§4.2 P2 gate: freshness floor p95 <= 40 ms at 15 k; peakRssMb budgeted",
    "impact": "§4.1 forward traversal, budgeted with P2's retrieval surface (R4)",
    "context": "§5 Budget (R4): context --identity p95 <= 400 ms and a stated peakRssMb ceiling",
    "tree": "§6 Budget (R4): tree and feature-drift each state an absolute p95 and peakRssMb",
    "drift": "§6 Budget (R4): tree and feature-drift each state an absolute p95 and peakRssMb",
}

# The whole R4 matrix in one mapping: the floor plus every per-command row. The gate and the
# coverage test both iterate THIS, so a traversal cannot be enforced in one and forgotten in the
# other.
TRAVERSAL_BUDGETS: dict[str, dict[str, float]] = {"floor": FLOOR_BUDGET, **COMMAND_BUDGETS}

# WHERE search.TRAVERSAL_LIMITS COMES FROM (§9's last open item).
#
# Until now: `{"maxNodes": 2000, "maxFanout": 500}` -- chosen constants, the audit's own word,
# derived from nothing and with no clock among them, so a walk whose nodes are individually
# expensive could only terminate on a node count it might never reach. `traversal_observations`
# now measures both regimes on the mixed corpus and these are the numbers that came out
# (macOS 15 / APFS, Apple silicon, Python 3.12, the 3 000-entry mixed fixture, 50 anchors per
# regime, --include-heuristic so the widest askable walk is the one measured):
#
#   regime  anchor        dir/depth   maxFanout  maxNodes  maxWalkMs      p95WalkMs
#   hub     CustomObject  incoming / 4    59        236     12.77-14.50    2.50-3.10
#   chain   ApexClass     outgoing / 2     2          4      0.02          0.01
#   leaf    CustomField   incoming / 1     0          0      0.00-0.01     0.00-0.01
#
# Fanout and node count are deterministic -- they are the graph's shape, identical in all six
# runs -- and only the walk times move. The hub regime is the only one that constrains anything,
# and it scales: fanout onto an object is the count of entries pointing at it, which grows with
# the corpus at a fixed object count. Projected linearly to the 15 k the plan budgets (§4.2, §5):
# fanout 295, nodes 1 180, walk 64-73 ms.
#
# THE RULE, applied uniformly: no limit may sit below 3x the worst legitimate walk this corpus
# produces projected to 15 k. That is the `headroom` column below and it is what the gate
# enforces. The shipped values sit further above it, because the two errors are not symmetric --
# a limit set too high costs bounded extra work on a rare walk, while a limit set too low edits
# an ordinary answer and the caller sees a truncation gap where there should have been a result.
#
#   limit        was    now    15 k projection   required (3x)   shipped multiple
#   maxFanout    500    2000        295              885              6.8x
#   maxNodes     2000   5000       1180             3540              4.2x
#   maxSeconds   --     2.0       64-73 ms         0.22 s            ~29x
#
# maxFanout 500 -> 2000. The old value cleared the 15 k projection by only 1.7x, and a real
# package hub is wider than this fixture's: one Account-shaped object carries hundreds of fields
# plus every Flow, Apex class and PermissionSet that touches it, none of which the synthetic mix
# reproduces. Raising it is close to free -- the cap bounds one frontier item's hop list, and
# total work is bounded by maxNodes and maxSeconds.
#
# maxNodes 2000 -> 5000. Same argument, same 1.7x: 2 000 was under twice the legitimate 15 k
# projection of 1 180. This changes no measured latency at BUDGET_ENTRIES, where the deepest walk
# reaches 236 nodes and never approaches either value; it buys headroom at target scale. Node
# count does not reach the caller either way -- every command caps rows at `--top` (25/50) long
# before serving -- so this bounds work, not output.
#
# maxSeconds: NEW, and the point of the exercise. 2.0 s sits deliberately ABOVE every per-command
# p95 ceiling in COMMAND_BUDGETS, the highest of which is context at 500 ms. That is not a second
# latency budget and must not be read as one: it is the terminator for the case a node count
# cannot bound -- a dense real graph where 5 000 nodes each cost a posting read -- so that a
# pathological walk ends on a clock with `limitsHit: ["time"]` instead of hanging the CLI. A
# machine ~29x slower than this one on the same corpus still does not trip it.
#
# WHAT THIS IS NOT. Every number is macOS on a synthetic mix. The plan names windows-latest as
# authoritative and the reference corpus is 189 components, not 3 000; the projection to 15 k is
# arithmetic, not measurement. The gate below is therefore one-sided -- it fails when a limit
# drops BELOW the measured legitimate regime, never when a walk is merely wide.
TRAVERSAL_LIMIT_BASIS: dict[str, dict[str, Any]] = {
    "maxFanout": {"observedKey": "projectedMaxFanoutAt15k", "headroom": 3.0},
    "maxNodes": {"observedKey": "projectedMaxNodesAt15k", "headroom": 3.0},
    # Milliseconds on the measured side, seconds on the configured side.
    "maxSeconds": {"observedKey": "projectedMaxWalkMsAt15k", "headroom": 3.0, "scale": 0.001},
}


def assert_traversal_limits(result: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Check `search.TRAVERSAL_LIMITS` still clears the regime it was derived from.

    One-sided on purpose. A walk that hits a limit is not a failure -- it is a disclosed
    truncation, and P2's hub-regime bar is stated as exactly that behaviour. What IS a failure is
    a limit that has drifted below the legitimate maximum this corpus produces at the size the
    plan budgets, because then an ordinary hub answer starts truncating and the limit stops being
    a safety valve and becomes a silent editor of results.
    """

    observed = result["traversalObserved"]
    configured = observed["configured"]
    report: dict[str, Any] = {"basis": "traversalObserved, projected to the plan's 15 k", "limits": {}}
    failures: list[str] = []
    if observed["entries"] != BUDGET_ENTRIES:
        # Same rule as the command table, for the same reason: the derivation in
        # TRAVERSAL_LIMIT_BASIS is stated at BUDGET_ENTRIES, and a 200-entry fixture has barely
        # a hub regime to measure. Projecting one up to 15 k would certify a limit against noise.
        return report, [
            f"TRAVERSAL LIMITS NOT APPLICABLE: TRAVERSAL_LIMIT_BASIS is stated at "
            f"{BUDGET_ENTRIES} entries and this run used {observed['entries']}."
        ]
    for limit, basis in TRAVERSAL_LIMIT_BASIS.items():
        worst = max(
            (regime[basis["observedKey"]] for regime in observed["regimes"].values()), default=0.0
        )
        required = worst * basis["headroom"] * basis.get("scale", 1.0)
        row = {
            "configured": configured[limit],
            "worstProjectedAt15k": worst,
            "headroom": basis["headroom"],
            "required": round(required, 4),
        }
        if configured[limit] < required:
            failures.append(
                f"TRAVERSAL LIMIT {limit} TOO TIGHT: {configured[limit]} < {required:.4g}, which "
                f"is {basis['headroom']}x the worst legitimate walk this corpus produces "
                f"projected to {observed['targetEntries']} entries "
                f"({worst:.4g} from {observed['entries']} measured). A limit under the regime it "
                "bounds truncates ordinary answers instead of pathological ones."
            )
            row["verdict"] = "TOO TIGHT"
        else:
            row["verdict"] = "PASS"
        report["limits"][limit] = row
    return report, failures


def assert_command_budgets(result: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Check every budgeted traversal against TRAVERSAL_BUDGETS. Returns (report, failures)."""

    entries = result["fixture"]["entries"]
    if entries != BUDGET_ENTRIES:
        return {}, [
            f"COMMAND BUDGETS NOT APPLICABLE: the table is stated at {BUDGET_ENTRIES} entries and "
            f"this run used {entries}. Re-run with --entries {BUDGET_ENTRIES}; a budget that "
            "accepts any fixture size can be met by running the benchmark smaller."
        ]
    report: dict[str, Any] = {
        "entries": entries,
        "planTraversals": sorted(PLAN_TRAVERSALS),
        "traversals": {},
    }
    failures: list[str] = []
    for name, budget in TRAVERSAL_BUDGETS.items():
        if name == "floor":
            # Measured by a different probe (`coldFloor`) and half-asserted elsewhere, so it
            # cannot share the per-command body -- but it is iterated from the same table, or a
            # row would exist in one place and be checked in the other.
            report["traversals"]["floor"] = assert_floor_memory(result, failures)
            continue
        cold = result["coldCommands"][name]
        measured_ms = cold["p95Ms"]
        measured_min_ms = round(cold["minUs"] / 1000, 1)
        measured_rss = cold["commandRssMb"]
        row: dict[str, Any] = {
            "basis": f"{cold['processes']} fresh `{name}` processes, cold first call in each",
            "minMs": measured_min_ms, "budgetMinMs": budget["minMs"],
            "p95Ms": measured_ms, "budgetMs": budget["p95Ms"],
            "commandRssMb": measured_rss, "budgetCommandRssMb": budget["commandRssMb"],
            "processRssMb": cold["peakRssMb"], "processRssScope": cold["peakRssScope"],
            "instrument": cold["peakRssSource"],
        }
        if measured_min_ms > budget["minMs"]:
            failures.append(
                f"{name.upper()} OVER LATENCY BUDGET (noise floor): {measured_min_ms:.1f} ms > "
                f"{budget['minMs']} ms at {entries} entries. The best of "
                f"{cold['processes']} cold processes cannot be explained by a busy runner."
            )
        if measured_ms > budget["p95Ms"]:
            failures.append(
                f"{name.upper()} OVER LATENCY BUDGET (p95): {measured_ms:.1f} ms > "
                f"{budget['p95Ms']} ms at {entries} entries"
            )
        if measured_rss is None:
            # Loud, never fatal: a platform with no peak-RSS instrument must not take the
            # latency half of the gate down with it.
            print(
                f"MEMORY UNMEASURED for {name}: {cold['peakRssSource']} -- the "
                f"{budget['commandRssMb']} MB ceiling was not verified on this platform",
                file=sys.stderr,
            )
        elif measured_rss > budget["commandRssMb"]:
            failures.append(
                f"{name.upper()} OVER MEMORY BUDGET: {measured_rss:.1f} MB > "
                f"{budget['commandRssMb']} MB added by one `{name}` call at {entries} entries"
            )
        if "postingBytesRead" in budget:
            measured_bytes = result["postingBytesReadPerQuery"][name]
            row["postingBytesRead"] = measured_bytes
            row["budgetPostingBytesRead"] = budget["postingBytesRead"]
            if measured_bytes > budget["postingBytesRead"]:
                failures.append(
                    f"{name.upper()} OVER POSTING-BYTE BUDGET: {measured_bytes} bytes > "
                    f"{budget['postingBytesRead']} at {entries} entries"
                )
        row["verdict"] = "OVER BUDGET" if any(
            failure.startswith(name.upper() + " ") for failure in failures
        ) else "PASS"
        report["traversals"][name] = row
    return report, failures


def assert_floor_memory(result: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    """Check the freshness floor's peak RSS against FLOOR_BUDGET, appending any failure.

    Separate from the per-command loop because the floor is measured by a different probe (a
    fresh `corpus_fingerprint` process, `coldFloor`) and its latency half is asserted elsewhere,
    by `--assert-floor-us`. Both halves are named in the row so a reader of the report can see
    where each is enforced instead of inferring that the missing one is unenforced -- which,
    until this row existed, it was.
    """

    cold = result["coldFloor"]
    measured_rss = cold["commandRssMb"]
    row: dict[str, Any] = {
        "basis": f"{cold['processes']} fresh `corpus_fingerprint` processes, cold first call",
        "commandRssMb": measured_rss,
        "budgetCommandRssMb": FLOOR_BUDGET["commandRssMb"],
        "processRssMb": cold["peakRssMb"], "processRssScope": cold["peakRssScope"],
        "instrument": cold["peakRssSource"],
        "latencyAssertedBy": "--assert-floor-us (a per-entry rate: this cost grows with N)",
        "perEntryUs": cold["perEntryUsFromMin"],
    }
    if measured_rss is None:
        # Same rule as the commands: no instrument is loud, never fatal, and never a pass by
        # silence. The latency gate must survive a platform that cannot measure memory.
        print(
            f"MEMORY UNMEASURED for floor: {cold['peakRssSource']} -- the "
            f"{FLOOR_BUDGET['commandRssMb']} MB ceiling was not verified on this platform",
            file=sys.stderr,
        )
        row["verdict"] = "UNMEASURED"
        return row
    if measured_rss > FLOOR_BUDGET["commandRssMb"]:
        failures.append(
            f"FLOOR OVER MEMORY BUDGET: {measured_rss:.1f} MB > "
            f"{FLOOR_BUDGET['commandRssMb']} MB added by one freshness-floor sweep at "
            f"{result['fixture']['entries']} entries"
        )
        row["verdict"] = "OVER BUDGET"
        return row
    row["verdict"] = "PASS"
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge_benchmark", description=__doc__)
    parser.add_argument("--entries", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument(
        "--cold-processes", type=int, default=COLD_PROCESSES,
        help="fresh processes per cold probe. Fewer than 21 turns the reported p95 into a "
        "maximum (see cold_probe), so lowering it makes every budget below flakier, not faster.",
    )
    parser.add_argument(
        "--assert-floor-us",
        type=float,
        default=None,
        help="fail if the COLD corpus_fingerprint call costs more than this many microseconds "
        "per entry, measured at the NOISE FLOOR (best of --cold-processes samples, fixed term "
        "subtracted). The freshness floor is paid by EVERY CLI invocation and grows with the "
        "corpus, so the per-entry cost is the thing that scales -- a budget stated at one "
        "corpus size can be met by running the benchmark smaller. The p95 of the same samples "
        "is reported beside it but not asserted: it measures the runner's tail, not the code.",
    )
    parser.add_argument(
        "--assert-command-budgets",
        action="store_true",
        help="fail if any traversal in TRAVERSAL_BUDGETS exceeds its absolute noise-floor "
        "latency, p95 latency, peak RSS or posting-byte ceiling -- including the freshness "
        "floor, whose memory ceiling is the only half of its budget not asserted by "
        "--assert-floor-us -- or if any search.TRAVERSAL_LIMITS value has drifted below the "
        "regime TRAVERSAL_LIMIT_BASIS derived it from. Each is scoped to ONE fresh command "
        "process, not "
        "to the benchmark process, which also writes the fixture and builds the index and would "
        f"certify a ceiling no command ever pays. Requires --entries {BUDGET_ENTRIES}.",
    )
    # Re-entry points, not user surface: `cold_probe` spawns this script to measure a first
    # call in an interpreter that has never touched the corpus.
    parser.add_argument("--cold-probe", choices=("fingerprint", *COMMAND_BUDGETS), default=None,
                        help=argparse.SUPPRESS)
    parser.add_argument("--cold-probe-root", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--cold-probe-identity", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.cold_probe:
        if not args.cold_probe_root:
            parser.error("--cold-probe requires --cold-probe-root")
        return cold_probe_child(
            Path(args.cold_probe_root), args.cold_probe, args.cold_probe_identity
        )

    result = run(args.entries, args.repeats, args.cold_processes)
    failures: list[str] = []

    if args.assert_floor_us is not None:
        # The NOISE FLOOR, not the p95. Measured on this repo's own fixture, the p95 of 21 cold
        # processes moved 4x with nothing but other work on the machine (8.3 -> 34.0 ms for an
        # unchanged corpus and unchanged code), so asserting it makes the build a function of
        # the runner. The minimum moves only when the code does. Both are in the block below.
        per_entry_us = result["coldFloor"]["perEntryUsFromMin"]
        over = per_entry_us > args.assert_floor_us
        result["floorBudget"] = {
            "basis": "cold first call in a fresh process, best of N samples (coldFloor.minUs)",
            "entries": result["fixture"]["entries"],
            "perEntryMicroseconds": per_entry_us,
            "budgetMicroseconds": args.assert_floor_us,
            "projectedMsAt15k": result["coldFloor"]["projectedMsAt15kFromMin"],
            # Reported, never asserted: the plan's own statistic, so a reader can see both the
            # code's cost and what the machine did to it on this run.
            "p95PerEntryMicroseconds": result["coldFloor"]["perEntryUs"],
            "p95ProjectedMsAt15k": result["coldFloor"]["projectedMsAt15k"],
            "verdict": "OVER BUDGET" if over else "PASS",
        }
        if over:
            failures.append(
                f"FLOOR OVER BUDGET: {per_entry_us:.2f} us/entry > {args.assert_floor_us} at "
                f"{result['fixture']['entries']} entries, measured at the noise floor "
                f"(projects to {result['coldFloor']['projectedMsAt15kFromMin']:.0f} ms at 15k "
                f"entries; the p95 of the same samples was "
                f"{result['coldFloor']['perEntryUs']:.2f} us/entry)"
            )

    if args.assert_command_budgets:
        report, budget_failures = assert_command_budgets(result)
        result["commandBudgets"] = report
        failures.extend(budget_failures)
        # Rides the same flag rather than taking one of its own: the traversal limits and the
        # command budgets are two halves of the same claim -- what a walk is allowed to cost --
        # and a second flag is a second thing a workflow can forget to pass.
        limit_report, limit_failures = assert_traversal_limits(result)
        result["traversalLimits"] = limit_report
        failures.extend(limit_failures)

    print(json.dumps(result, indent=2, sort_keys=True))
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
