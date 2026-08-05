#!/usr/bin/env python3
"""Reusable governed-state primitives: path confinement, leases and journalled commits.

`work_record.py` already had atomic replacement, hashing and schema validation. This module
adds the three things a stateful Design Case runtime needs and the work record never had:

* **Windows-safe path confinement** — drive-relative, UNC, alternate-data-stream, reserved-name,
  trailing dot/space, traversal, control-character and case-fold-collision rejection, plus a
  worst-case path budget check before the first write.
* **An advisory lease per case** — claimed by exclusive create (`O_CREAT | O_EXCL`), carrying a
  random owner nonce. An expired lease is never overwritten in place: a contender renames it to a
  unique quarantine name and then competes again for exclusive creation. PID is never authority.
* **A two-file journalled commit** — `record.json` and `design.md` are replaced together or not at
  all, and a crash leaves the complete old pair or the complete new pair, never a mix.

Everything is standard library. Nothing here knows what a Design Case means; that is
`solution_design_core.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


LEASE_SCHEMA_VERSION = 1
DEFAULT_LEASE_TTL_SECONDS = 120
DEFAULT_HEARTBEAT_SECONDS = 30
DEFAULT_CLOCK_SKEW_SECONDS = 30
# Windows MAX_PATH. The budget check refuses a deep root before the first write instead of
# failing halfway through a candidate directory.
WINDOWS_PATH_BUDGET = 260
# Longest relative path the case tree can produce: candidates/<candidate-id>/design.md plus
# generous identifier headroom.
WORST_CASE_RELATIVE_LENGTH = 120

RESERVED_WINDOWS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
RETRYABLE_ERRNOS = frozenset({13, 16, 32})  # EACCES, EBUSY, ERROR_SHARING_VIOLATION on Windows
REPLACE_RETRY_ATTEMPTS = 8
REPLACE_RETRY_BASE_SECONDS = 0.02


class GovernedStateError(RuntimeError):
    """A safe, user-actionable governed-state failure."""


class LeaseUnavailable(GovernedStateError):
    """Another runtime currently owns this case in this checkout."""


# --------------------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise GovernedStateError(f"{label} is not a valid date-time") from exc
    if parsed.tzinfo is None:
        raise GovernedStateError(f"{label} must include a timezone")
    return parsed


# --------------------------------------------------------------------------------------
# Path confinement (PATH-01)
# --------------------------------------------------------------------------------------


def _segment_problem(segment: str) -> str | None:
    if not segment:
        return "empty path segment"
    if segment in (".", ".."):
        return "path traversal segment"
    if ":" in segment:
        return "alternate data stream or drive syntax in a path segment"
    if any(character in segment for character in '<>"|?*\\'):
        return "character reserved by Windows in a path segment"
    if any(ord(character) < 32 for character in segment):
        return "control character in a path segment"
    if segment != segment.rstrip(". "):
        return "path segment ends with a dot or space"
    stem = segment.split(".", 1)[0].upper()
    if stem in RESERVED_WINDOWS_NAMES:
        return f"reserved Windows device name '{stem}'"
    return None


def safe_relative_path(raw: str) -> str:
    """Normalize a workspace-relative path or refuse it.

    Refusal is deliberate on both platforms: a path that is legal on macOS but hostile on
    Windows must fail identically everywhere, or the release-blocking platform finds it first.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise GovernedStateError("path must be a non-empty string")
    candidate = unicodedata.normalize("NFC", raw).replace("\\", "/")
    if candidate.startswith("/") or candidate.startswith("//"):
        raise GovernedStateError(f"absolute or UNC path is not allowed: {raw!r}")
    if len(candidate) > 1 and candidate[1] == ":":
        raise GovernedStateError(f"drive-relative path is not allowed: {raw!r}")
    parts = [part for part in PurePosixPath(candidate).parts]
    if not parts:
        raise GovernedStateError(f"path resolves to nothing: {raw!r}")
    for segment in parts:
        problem = _segment_problem(segment)
        if problem is not None:
            raise GovernedStateError(f"{problem}: {raw!r}")
    return "/".join(parts)


def contained_path(root: Path, relative: str) -> Path:
    """Resolve inside `root` or refuse. Symlink and junction escapes are rejected."""
    normalized = safe_relative_path(relative)
    resolved_root = root.resolve()
    candidate = (resolved_root / normalized).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise GovernedStateError(f"path escapes the workspace root: {relative!r}") from exc
    # A component that exists as a symlink must not point outside the root either.
    walker = resolved_root
    for segment in normalized.split("/"):
        walker = walker / segment
        if walker.is_symlink():
            target = walker.resolve()
            try:
                target.relative_to(resolved_root)
            except ValueError as exc:
                raise GovernedStateError(
                    f"path traverses a symlink that escapes the workspace root: {relative!r}"
                ) from exc
    return candidate


def assert_case_fold_unique(paths: Iterable[str]) -> None:
    """Two authoritative paths that differ only by case collide on Windows and macOS."""
    seen: dict[str, str] = {}
    for path in paths:
        folded = unicodedata.normalize("NFC", path).casefold()
        if folded in seen and seen[folded] != path:
            raise GovernedStateError(
                f"case-insensitive path collision between {seen[folded]!r} and {path!r}"
            )
        seen[folded] = path


def assert_path_budget(root: Path, relative_headroom: int = WORST_CASE_RELATIVE_LENGTH) -> None:
    """Refuse a root so deep that the worst-case case path would exceed the Windows budget."""
    projected = len(str(root.resolve())) + 1 + relative_headroom
    if projected > WINDOWS_PATH_BUDGET:
        raise GovernedStateError(
            f"workspace root is too deep: the worst-case Design Case path would be {projected} "
            f"characters, over the {WINDOWS_PATH_BUDGET}-character Windows budget"
        )


# --------------------------------------------------------------------------------------
# Atomic write with a bounded Windows retry
# --------------------------------------------------------------------------------------


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def write_temp(target: Path, payload: bytes) -> Path:
    """Write payload to a hashed temp file beside its target, on the same filesystem."""
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()[:12]
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.{digest}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(name)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


def replace_with_retry(source: Path, target: Path) -> None:
    """`os.replace` with a bounded retry for Windows sharing violations and antivirus races.

    Retry is bounded on purpose: an unbounded retry turns a held handle into a hang, and the
    prior complete pair stays current either way.
    """
    last: OSError | None = None
    for attempt in range(REPLACE_RETRY_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except OSError as error:
            if error.errno not in RETRYABLE_ERRNOS:
                raise
            last = error
            time.sleep(REPLACE_RETRY_BASE_SECONDS * (2**attempt))
    raise GovernedStateError(
        f"could not replace {target.name} after {REPLACE_RETRY_ATTEMPTS} attempts: {last}"
    )


# --------------------------------------------------------------------------------------
# Lease
# --------------------------------------------------------------------------------------


class Lease:
    """An advisory per-case lease for one checkout. Never described as a distributed lock."""

    def __init__(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        ttl_seconds: int,
        clock_skew_seconds: int,
    ) -> None:
        self.path = path
        self.payload = payload
        self.ttl_seconds = ttl_seconds
        self.clock_skew_seconds = clock_skew_seconds

    @property
    def nonce(self) -> str:
        return self.payload["ownerNonce"]

    @staticmethod
    def path_for(runtime_root: Path, case_path: Path) -> Path:
        digest = hashlib.sha256(str(case_path.resolve()).encode("utf-8")).hexdigest()[:32]
        return runtime_root / "leases" / f"{digest}.lease.json"

    @classmethod
    def acquire(
        cls,
        runtime_root: Path,
        case_path: Path,
        *,
        ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
        now: datetime | None = None,
    ) -> "Lease":
        moment = now or utc_now()
        path = cls.path_for(runtime_root, case_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": LEASE_SCHEMA_VERSION,
            "casePathDigest": hashlib.sha256(
                str(case_path.resolve()).encode("utf-8")
            ).hexdigest(),
            "host": os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "unknown"),
            "pid": os.getpid(),
            "ownerNonce": secrets.token_hex(16),
            "acquiredAt": iso(moment),
            "renewedAt": iso(moment),
            "expiresAt": iso(moment + timedelta(seconds=ttl_seconds)),
        }
        for attempt in range(3):
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                cls._quarantine_if_expired(
                    path, moment=moment, clock_skew_seconds=clock_skew_seconds
                )
                if attempt == 2:
                    raise LeaseUnavailable(
                        f"another runtime owns this case in this checkout: {case_path.name}"
                    )
                continue
            except OSError as error:
                if error.errno in RETRYABLE_ERRNOS and attempt < 2:
                    time.sleep(REPLACE_RETRY_BASE_SECONDS * (2**attempt))
                    continue
                raise
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(json.dumps(payload, sort_keys=True).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(path.parent)
            return cls(
                path, payload, ttl_seconds=ttl_seconds, clock_skew_seconds=clock_skew_seconds
            )
        raise LeaseUnavailable(f"could not claim the lease for {case_path.name}")

    @staticmethod
    def _quarantine_if_expired(
        path: Path, *, moment: datetime, clock_skew_seconds: int
    ) -> None:
        """Rename an expired lease out of the way; never overwrite one in place.

        A lost rename race means another contender got there first, so this returns quietly and
        the caller competes again for exclusive creation.
        """
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            try:
                expires = parse_iso(payload.get("expiresAt", ""), "lease expiresAt")
            except GovernedStateError:
                expires = None
            if expires is not None and moment < expires + timedelta(seconds=clock_skew_seconds):
                return  # still live under the clock-skew tolerance
        quarantine = path.with_name(f"{path.name}.stale.{secrets.token_hex(8)}")
        try:
            os.replace(path, quarantine)
        except OSError:
            return

    def still_owned(self, *, now: datetime | None = None) -> bool:
        """Re-read the lease file and confirm this process still owns it and it has not expired."""
        moment = now or utc_now()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if payload.get("ownerNonce") != self.nonce:
            return False
        try:
            return moment < parse_iso(payload.get("expiresAt", ""), "lease expiresAt")
        except GovernedStateError:
            return False

    def renew(self, *, now: datetime | None = None) -> None:
        moment = now or utc_now()
        if not self.still_owned(now=moment):
            raise LeaseUnavailable("the lease was reclaimed; reload before mutating this case")
        self.payload["renewedAt"] = iso(moment)
        self.payload["expiresAt"] = iso(moment + timedelta(seconds=self.ttl_seconds))
        temporary = write_temp(self.path, json.dumps(self.payload, sort_keys=True).encode("utf-8"))
        replace_with_retry(temporary, self.path)

    def release(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("ownerNonce") != self.nonce:
            return  # someone else legitimately reclaimed it; never delete their lease
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> "Lease":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


# --------------------------------------------------------------------------------------
# Journalled multi-file commit
# --------------------------------------------------------------------------------------


def journal_path(runtime_root: Path, case_path: Path) -> Path:
    digest = hashlib.sha256(str(case_path.resolve()).encode("utf-8")).hexdigest()[:32]
    return runtime_root / "journals" / f"{digest}.journal.json"


def commit_pair(
    runtime_root: Path,
    case_path: Path,
    writes: Sequence[tuple[Path, bytes]],
    *,
    lease: Lease | None = None,
    now: datetime | None = None,
) -> None:
    """Replace several files as one unit, recoverable after a crash at any point.

    Order matters: every temp file is written and fsynced, then the journal records the exact
    (target, temp, digest) triples, then the replaces run, then the journal is removed. A crash
    before the journal exists leaves only orphan temp files; a crash after it leaves a journal
    that `recover` can finish.
    """
    if lease is not None and not lease.still_owned(now=now):
        raise LeaseUnavailable(
            "the lease expired or was reclaimed before commit; nothing was written"
        )
    staged: list[tuple[Path, Path, str]] = []
    try:
        for target, payload in writes:
            temporary = write_temp(target, payload)
            staged.append((target, temporary, hashlib.sha256(payload).hexdigest()))
    except BaseException:
        for _target, temporary, _digest in staged:
            temporary.unlink(missing_ok=True)
        raise

    journal = journal_path(runtime_root, case_path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schemaVersion": 1,
        "casePath": str(case_path),
        "createdAt": iso(now or utc_now()),
        "writes": [
            {"target": str(target), "temp": str(temporary), "sha256": digest}
            for target, temporary, digest in staged
        ],
    }
    temporary_journal = write_temp(journal, json.dumps(record, sort_keys=True).encode("utf-8"))
    replace_with_retry(temporary_journal, journal)

    # The last freshness check before any target changes: a paused process must not commit after
    # another runtime safely reclaimed the case.
    if lease is not None and not lease.still_owned(now=now):
        journal.unlink(missing_ok=True)
        for _target, temporary, _digest in staged:
            temporary.unlink(missing_ok=True)
        raise LeaseUnavailable(
            "the lease was reclaimed while staging; nothing was written"
        )

    for target, temporary, _digest in staged:
        replace_with_retry(temporary, target)
        _fsync_directory(target.parent)
    journal.unlink(missing_ok=True)


def recover(runtime_root: Path, case_path: Path) -> str:
    """Finish or discard an interrupted commit. Never leaves a mixed pair.

    Returns `completed`, `rolled-back` or `clean`.
    """
    journal = journal_path(runtime_root, case_path)
    if not journal.is_file():
        return "clean"
    try:
        record = json.loads(journal.read_text(encoding="utf-8"))
        writes = record["writes"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        journal.unlink(missing_ok=True)
        return "rolled-back"

    staged: list[tuple[Path, Path]] = []
    for entry in writes:
        temporary = Path(entry["temp"])
        target = Path(entry["target"])
        if not temporary.is_file():
            # A temp file already consumed by a completed replace, or lost. If any temp is
            # missing we cannot prove the new pair, so verify the target instead.
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]:
                continue
            for _target, leftover in staged:
                leftover.unlink(missing_ok=True)
            journal.unlink(missing_ok=True)
            return "rolled-back"
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != entry["sha256"]:
            for _target, leftover in staged:
                leftover.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
            journal.unlink(missing_ok=True)
            return "rolled-back"
        staged.append((target, temporary))

    for target, temporary in staged:
        replace_with_retry(temporary, target)
        _fsync_directory(target.parent)
    journal.unlink(missing_ok=True)
    return "completed"


def sweep_runtime_scratch(runtime_root: Path, *, older_than_seconds: int = 86_400) -> int:
    """Remove quarantined leases and orphan temp files older than the retention window."""
    removed = 0
    cutoff = time.time() - older_than_seconds
    for directory in ("leases", "journals"):
        base = runtime_root / directory
        if not base.is_dir():
            continue
        for path in base.iterdir():
            if ".stale." not in path.name and not path.name.endswith(".tmp"):
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    return removed
