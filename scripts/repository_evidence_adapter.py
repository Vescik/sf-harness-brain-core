#!/usr/bin/env python3
"""Executor-authored repository evidence bound to an exact Git blob.

`SAFE-CLAIM-001` used to allow a verified positive claim about intended repository source state
only from an approved-current, source-exact Knowledge Entry. A model raw-file read was never
verification and still is not. This adapter is the second admitted authority: it reads the exact
tracked blob at a full commit SHA through the Git object database and emits a receipt bound to
repository identity, commit, normalized path, blob OID, range, content digest and coverage.

Reading by object ID rather than by working-tree path is the point. It removes the
read-versus-resolve TOCTOU window, it cannot follow a symlink or junction out of the repository,
and it behaves identically on Windows and macOS. A dirty working tree is reported separately and
never described as the commit state.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    from governed_state import GovernedStateError, safe_relative_path
except ModuleNotFoundError:  # imported as scripts.repository_evidence_adapter by unit tests
    from scripts.governed_state import GovernedStateError, safe_relative_path


FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
BLOB_MODES = frozenset({"100644", "100755"})
MAX_BLOB_BYTES = 2_000_000
GIT_TIMEOUT_SECONDS = 30


class RepositoryEvidenceError(RuntimeError):
    """A safe, user-actionable repository-evidence failure."""


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        text=True,
        capture_output=True,
        check=False,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RepositoryEvidenceError(
            f"git {arguments[0]} failed: {result.stderr.strip().splitlines()[:1]}"
        )
    return result.stdout


def _validated_path(raw: str) -> str:
    if raw.startswith("-"):
        raise RepositoryEvidenceError("option-like paths are rejected")
    try:
        return safe_relative_path(raw)
    except GovernedStateError as exc:
        raise RepositoryEvidenceError(str(exc)) from exc


def resolve_blob(repository: Path, commit: str, path: str) -> dict[str, Any]:
    """Resolve one regular blob at an exact commit, or refuse.

    Refuses: short/ambiguous commits, symlink and submodule modes, directories, option-like
    paths, traversal, drive/UNC/ADS syntax and anything the tree does not contain.
    """
    if not FULL_COMMIT.match(commit or ""):
        raise RepositoryEvidenceError("a full 40-character commit SHA is required")
    normalized = _validated_path(path)
    listing = _git(repository, "ls-tree", "-z", commit, "--", normalized)
    entries = [entry for entry in listing.split("\0") if entry]
    if not entries:
        raise RepositoryEvidenceError(f"{normalized} does not exist at {commit[:12]}")
    if len(entries) > 1:
        raise RepositoryEvidenceError(f"{normalized} is ambiguous at {commit[:12]}")
    header, _, listed_path = entries[0].partition("\t")
    mode, kind, oid = header.split(" ", 2)
    if kind != "blob":
        raise RepositoryEvidenceError(
            f"{normalized} is a {kind} at {commit[:12]}, not a regular file"
        )
    if mode not in BLOB_MODES:
        raise RepositoryEvidenceError(
            f"{normalized} has mode {mode} at {commit[:12]}; symlinks and submodules are rejected"
        )
    if listed_path != normalized:
        raise RepositoryEvidenceError(
            f"git resolved {listed_path!r} for the requested {normalized!r}; refusing an alias"
        )
    size = int(_git(repository, "cat-file", "-s", oid).strip())
    if size > MAX_BLOB_BYTES:
        raise RepositoryEvidenceError(
            f"{normalized} is {size} bytes at {commit[:12]}, over the {MAX_BLOB_BYTES}-byte bound"
        )
    return {"mode": mode, "oid": oid, "path": normalized, "size": size}


def _read_blob(repository: Path, oid: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "blob", oid],
        capture_output=True,
        check=False,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RepositoryEvidenceError(f"could not read blob {oid[:12]}")
    return result.stdout


def working_tree_drift(repository: Path, path: str, oid: str) -> bool:
    """True when the working-tree file differs from the committed blob.

    Drift never blocks the receipt; it blocks the *claim* that the receipt represents the
    current workspace.
    """
    candidate = repository / path
    if not candidate.is_file() or candidate.is_symlink():
        return True
    try:
        current = _git(repository, "hash-object", "--", path).strip()
    except RepositoryEvidenceError:
        return True
    return current != oid


def repository_identity(repository: Path) -> str:
    """A stable, privacy-preserving repository identity: the digest of the first commit."""
    root = _git(repository, "rev-list", "--max-parents=0", "HEAD").strip().splitlines()
    if not root:
        raise RepositoryEvidenceError("repository has no root commit")
    return "sha256:" + hashlib.sha256(root[-1].encode("utf-8")).hexdigest()


def capture(
    repository: Path,
    commit: str,
    path: str,
    *,
    first_line: int | None = None,
    last_line: int | None = None,
) -> dict[str, Any]:
    """Return the executor-authored source facts for one blob or line range.

    The payload deliberately carries digests, coverage and a range descriptor — never the file
    content. Turning source text into durable design state is the model's job through a
    decision, not the adapter's through a copy.
    """
    entry = resolve_blob(repository, commit, path)
    payload = _read_blob(repository, entry["oid"])
    text = payload.decode("utf-8", errors="replace")
    lines = text.split("\n")
    coverage = "full"
    selected = text
    descriptor = None
    if first_line is not None or last_line is not None:
        start = max(1, first_line or 1)
        end = min(len(lines), last_line or len(lines))
        if start > end:
            raise RepositoryEvidenceError("line range is empty")
        selected = "\n".join(lines[start - 1 : end])
        coverage = "range-bounded"
        descriptor = f"L{start}-L{end}"
    return {
        "repositoryIdentity": repository_identity(repository),
        "commit": commit,
        "path": entry["path"],
        "blobOid": entry["oid"],
        "mode": entry["mode"],
        "range": descriptor,
        "coverage": coverage,
        "contentDigest": "sha256:" + hashlib.sha256(selected.encode("utf-8")).hexdigest(),
        "blobDigest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "lineCount": len(lines),
        "byteSize": entry["size"],
        "workingTreeDrift": working_tree_drift(repository, entry["path"], entry["oid"]),
    }
