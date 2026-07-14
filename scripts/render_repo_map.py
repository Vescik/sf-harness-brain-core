#!/usr/bin/env python3
"""Render the deterministic repository atlas: .ai/repo-map.md and .ai/repo-map.json.

The atlas is the agent-facing orientation map (directory purposes, role -> files matrix,
skills/contracts/commands catalogs, resume pointers). Everything except the seeded directory
purposes and resume lines is parsed from existing frontmatter and headings, so the map can never
drift from its sources; `render --check` fails when the committed artifacts drift, mirroring
`knowledge_registry.py render-indexes --check`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "config/repo-map-seed.json"
MAP_MD_PATH = ROOT / ".ai/repo-map.md"
MAP_JSON_PATH = ROOT / ".ai/repo-map.json"
WORD_BUDGET = 800
ONE_LINER_WORDS = 7
LINK_RE = re.compile(r"\]\(([^)]+)\)")


class RepoMapError(RuntimeError):
    pass


def frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise RepoMapError(f"{path}: unterminated frontmatter")
    data = yaml.safe_load(text[4:end])
    if not isinstance(data, dict):
        raise RepoMapError(f"{path}: frontmatter must be a mapping")
    return data, text[end + 5 :]


def one_liner(text: str, limit: int = ONE_LINER_WORDS) -> str:
    sentence = text.strip().split(". ", 1)[0].rstrip(".")
    words = sentence.split()
    if len(words) > limit:
        return " ".join(words[:limit]) + " …"
    return sentence


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_directories() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        raise RepoMapError(f"git ls-files failed: {completed.stderr.strip()}")
    prefixes: set[str] = set()
    for line in completed.stdout.splitlines():
        parts = Path(line).parts[:-1]
        for depth in range(1, len(parts) + 1):
            prefixes.add("/".join(parts[:depth]))
    return prefixes


def load_seed() -> dict[str, Any]:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if seed.get("kind") != "repo-map-seed" or seed.get("schemaVersion") != 1:
        raise RepoMapError(f"{SEED_PATH}: unsupported seed kind/version")
    tracked = tracked_directories()
    top_level = {prefix for prefix in tracked if "/" not in prefix}
    seeded = {entry["path"] for entry in seed["directories"]}
    missing = sorted(top_level - seeded)
    if missing:
        raise RepoMapError(f"seed lacks top-level tracked directories: {missing}")
    stale = sorted(path for path in seeded if path not in tracked)
    if stale:
        raise RepoMapError(f"seed names directories with no tracked files: {stale}")
    return seed


def collect_agents() -> list[dict[str, Any]]:
    agents = []
    for path in sorted((ROOT / ".github/agents").glob("*.agent.md")):
        data, body = frontmatter(path)
        loads = {"instructions": set(), "contracts": set(), "skills": set()}
        for target in LINK_RE.findall(body):
            clean = target.split("#", 1)[0]
            if "/instructions/" in clean and clean.endswith(".md"):
                loads["instructions"].add(Path(clean).name.removesuffix(".instructions.md"))
            elif "/contracts/" in clean:
                loads["contracts"].add(Path(clean).stem)
            elif "/skills/" in clean:
                loads["skills"].add(Path(clean).parent.name)
        agents.append(
            {
                "name": str(data.get("name", path.stem)),
                "description": str(data.get("description", "")),
                "handoffs": sorted(
                    str(handoff.get("agent", "")) for handoff in data.get("handoffs", []) or []
                ),
                "loads": {key: sorted(value) for key, value in loads.items()},
                "path": path.relative_to(ROOT).as_posix(),
            }
        )
    return agents


def collect_skills() -> list[dict[str, Any]]:
    return [
        {
            "name": str(data.get("name", path.parent.name)),
            "description": str(data.get("description", "")),
            "path": path.relative_to(ROOT).as_posix(),
        }
        for path in sorted((ROOT / ".github/skills").glob("*/SKILL.md"))
        for data, _ in [frontmatter(path)]
    ]


def collect_prompts() -> list[dict[str, Any]]:
    return [
        {
            "name": str(data.get("name", path.name.removesuffix(".prompt.md"))),
            "description": str(data.get("description", "")),
            "agent": str(data.get("agent", "")),
            "argumentHint": str(data.get("argument-hint", "")),
            "path": path.relative_to(ROOT).as_posix(),
        }
        for path in sorted((ROOT / ".github/prompts").glob("*.prompt.md"))
        for data, _ in [frontmatter(path)]
    ]


def collect_instructions() -> list[dict[str, Any]]:
    records = []
    for path in sorted((ROOT / ".github/instructions").glob("*.instructions.md")):
        data, _ = frontmatter(path)
        record = {
            "name": path.name.removesuffix(".instructions.md"),
            "description": str(data.get("description", "")),
            "path": path.relative_to(ROOT).as_posix(),
        }
        if data.get("applyTo"):
            record["applyTo"] = str(data["applyTo"])
        records.append(record)
    return records


def collect_contracts() -> list[dict[str, Any]]:
    records = []
    for path in sorted((ROOT / ".ai/contracts").glob("*.md")):
        title = ""
        summary = ""
        for paragraph in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
            stripped = paragraph.strip()
            if not stripped:
                continue
            if not title and stripped.startswith("# "):
                title = stripped.splitlines()[0][2:]
                continue
            if title and not stripped.startswith(("#", "Status:", "Schema version:", "|", "-", "*")):
                summary = " ".join(stripped.split())
                break
        records.append(
            {
                "name": path.stem,
                "title": title,
                "summary": summary,
                "path": path.relative_to(ROOT).as_posix(),
            }
        )
    return records


def build_model() -> dict[str, Any]:
    seed = load_seed()
    model = {
        "schemaVersion": 1,
        "kind": "repo-map",
        "directories": seed["directories"],
        "resumeHere": seed["resumeHere"],
        "agents": collect_agents(),
        "skills": collect_skills(),
        "prompts": collect_prompts(),
        "instructions": collect_instructions(),
        "contracts": collect_contracts(),
    }
    digests = {SEED_PATH.relative_to(ROOT).as_posix(): file_digest(SEED_PATH)}
    for section in ("agents", "skills", "prompts", "instructions", "contracts"):
        for record in model[section]:
            digests[record["path"]] = file_digest(ROOT / record["path"])
    model["sourceDigests"] = dict(sorted(digests.items()))
    return model


def render_md(model: dict[str, Any]) -> str:
    lines = [
        "# Repository Atlas — Generated Map",
        "",
        "Generated by `scripts/render_repo_map.py`; do not hand-edit. Orient here before exploring;",
        "the deep directory tree lives in `docs/workspace-topology.md`.",
        "",
        "## Layout",
        "",
        "| Path | Purpose |",
        "|---|---|",
    ]
    for entry in model["directories"]:
        lines.append(f"| `{entry['path']}` | {entry['purpose']} |")
    lines.extend(["", "## Roles (`.github/agents/`)", ""])
    for agent in model["agents"]:
        loads = agent["loads"]
        parts = []
        if loads["instructions"]:
            parts.append("instructions: " + ", ".join(loads["instructions"]))
        if loads["contracts"]:
            parts.append("contracts: " + ", ".join(loads["contracts"]))
        if loads["skills"]:
            parts.append("skills: " + ", ".join(loads["skills"]))
        handoffs = f" Hands off to: {', '.join(agent['handoffs'])}." if agent["handoffs"] else ""
        lines.append(
            f"- **{agent['name']}** — {one_liner(agent['description'])}. "
            f"Loads {'; '.join(parts)}.{handoffs}"
        )
    lines.extend(["", "## Skills (`.github/skills/`)", ""])
    for skill in model["skills"]:
        lines.append(f"- `{skill['name']}` — {one_liner(skill['description'])}")
    lines.extend(["", "## Commands (`.github/prompts/`, public)", ""])
    for prompt in model["prompts"]:
        lines.append(f"- `/{prompt['name']}` → {prompt['agent']}")
    lines.extend(["", "## Contracts (`.ai/contracts/`)", ""])
    for contract in model["contracts"]:
        lines.append(f"- `{contract['name']}` — {one_liner(contract['summary'])}")
    lines.extend(["", "## Instructions (`.github/instructions/`)", ""])
    for instruction in model["instructions"]:
        apply_to = f" (applyTo: `{instruction['applyTo']}`)" if "applyTo" in instruction else ""
        lines.append(f"- `{instruction['name']}` — {one_liner(instruction['description'])}{apply_to}")
    lines.extend(["", "## Resume here", ""])
    for line in model["resumeHere"]:
        lines.append(f"- {line}")
    lines.append("")
    text = "\n".join(lines)
    count = word_count(text)
    if count > WORD_BUDGET:
        raise RepoMapError(f"repo-map.md exceeds the {WORD_BUDGET}-word budget: {count} words")
    return text


def render_json(model: dict[str, Any], md_words: int) -> str:
    payload = dict(model, wordCount=md_words)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render(check: bool) -> dict[str, Any]:
    model = build_model()
    md_text = render_md(model)
    json_text = render_json(model, word_count(md_text))
    drift = []
    for path, expected in ((MAP_MD_PATH, md_text), (MAP_JSON_PATH, json_text)):
        if check:
            actual = path.read_text(encoding="utf-8") if path.is_file() else ""
            if actual != expected:
                try:
                    drift.append(path.relative_to(ROOT).as_posix())
                except ValueError:
                    drift.append(str(path))
        else:
            path.write_text(expected, encoding="utf-8")
    if drift:
        raise RepoMapError(f"generated repo map drifted: {drift}")
    return {
        "mode": "check" if check else "write",
        "words": word_count(md_text),
        "agents": len(model["agents"]),
        "skills": len(model["skills"]),
        "prompts": len(model["prompts"]),
        "contracts": len(model["contracts"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render_cmd = commands.add_parser("render")
    render_cmd.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = render(args.check)
    except (RepoMapError, OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
