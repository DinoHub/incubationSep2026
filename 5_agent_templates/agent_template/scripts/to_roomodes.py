#!/usr/bin/env python3
"""Port a Claude-Code-style agent template (.claude/agents/*.md) into a Roo
Code custom mode entry in .roomodes.

Roo Code doesn't read one-file-per-agent directories the way Claude Code,
Cursor, and OpenCode do -- all of its custom modes live as entries in a single
YAML file, .roomodes, at the project root. This script does the structural
translation so you don't hand-copy it:

    name          -> slug, and a humanized display `name`
    description   -> description (first sentence) + whenToUse (full text)
    body          -> roleDefinition (first paragraph) + customInstructions (rest)
    tools         -> groups: read / edit / command / mcp (coarse by design --
                     Roo has no per-tool-name allowlist, so this is a widening
                     translation, not an exact one; review the result)

Roo has no `model` field in .roomodes -- model selection is bound per-mode in
Roo's own settings UI, not version-controlled, so this script doesn't set one.

Requires PyYAML:  pip install pyyaml

Usage:
    python to_roomodes.py ../../../.claude/agents/example-agent.md
    python to_roomodes.py path/to/agent.md --roomodes /path/to/.roomodes
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "error: this script requires PyYAML. Install it with: pip install pyyaml",
        file=sys.stderr,
    )
    raise SystemExit(1)

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

# Claude/Cursor tool names -> Roo's coarse permission groups.
TOOL_GROUP_MAP = {
    "read": {"Read", "Grep", "Glob"},
    "edit": {"Write", "Edit", "NotebookEdit"},
    "command": {"Bash"},
}


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def parse_agent_file(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        die(f"{path} has no YAML frontmatter (expected a leading '---' block)")
    frontmatter = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    if not isinstance(frontmatter, dict) or "name" not in frontmatter or "description" not in frontmatter:
        die(f"{path} frontmatter must at least have 'name' and 'description'")
    return frontmatter, body


def humanize(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-"))


def split_role(body: str) -> tuple[str, str]:
    """First paragraph becomes roleDefinition; the rest becomes customInstructions."""
    parts = body.split("\n\n", 1)
    role = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return role, rest


def first_sentence(text: str) -> str:
    match = re.search(r"(.+?[.!?])(\s|$)", text.strip())
    return match.group(1) if match else text.strip()


def to_groups(tools_field: str | None) -> list[str]:
    if not tools_field:
        # No allowlist means "inherits everything" in Claude Code/Cursor --
        # give the mode the full set rather than guessing a narrower default.
        return ["read", "edit", "command", "mcp"]
    names = {t.strip() for t in tools_field.split(",")}
    groups = [group for group, matches in TOOL_GROUP_MAP.items() if names & matches]
    if any(name.startswith("mcp__") or name == "Agent" for name in names):
        groups.append("mcp")
    return groups or ["read"]


def build_entry(frontmatter: dict, body: str) -> dict:
    name = frontmatter["name"]
    description = frontmatter["description"]
    role, rest = split_role(body)
    entry = {
        "slug": name,
        "name": humanize(name),
        "description": first_sentence(description),
        "whenToUse": description,
        "roleDefinition": role,
        "groups": to_groups(frontmatter.get("tools")),
    }
    if rest:
        entry["customInstructions"] = rest
    return entry


def upsert(roomodes_path: Path, entry: dict) -> None:
    if roomodes_path.exists():
        doc = yaml.safe_load(roomodes_path.read_text(encoding="utf-8")) or {}
    else:
        doc = {}
    modes = doc.setdefault("customModes", [])
    existing_index = next((i for i, m in enumerate(modes) if m.get("slug") == entry["slug"]), None)
    if existing_index is not None:
        modes[existing_index] = entry
        action = "updated"
    else:
        modes.append(entry)
        action = "added"
    roomodes_path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(f"{action} mode {entry['slug']!r} in {roomodes_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("agent_file", type=Path, help="Path to the .claude/agents/*.md file to port")
    parser.add_argument(
        "--roomodes",
        type=Path,
        default=Path(".roomodes"),
        help="Target .roomodes file (default: ./.roomodes)",
    )
    args = parser.parse_args()

    if not args.agent_file.exists():
        die(f"{args.agent_file} not found")
    frontmatter, body = parse_agent_file(args.agent_file)
    entry = build_entry(frontmatter, body)
    upsert(args.roomodes, entry)


if __name__ == "__main__":
    main()
