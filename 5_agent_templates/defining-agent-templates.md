# Defining Agent Templates

This guide is about **agent templates**: the file that turns a general-purpose
coding assistant into a named specialist — a role, a system prompt, and a
slice of tool access — that gets delegated to rather than loaded into the main
conversation. It builds one real template, then compares how four harnesses
— **Claude Code**, **Cursor**, **OpenCode**, and **Roo Code** — each read that
idea, so one template travels across as many of them as practical.

Cross-harness portability is the secondary goal here, not the primary one —
get a solid Claude Code agent first; the comparison and porting notes below
exist so you aren't starting from scratch on the others, not so every field
round-trips perfectly. The field names and behavior here were checked against
the current Claude Code, Cursor, OpenCode, and Roo Code docs as of **August
2026**; sources are listed at the end.

## Contents

- [Where an agent sits next to a skill and an MCP server](#where-an-agent-sits-next-to-a-skill-and-an-mcp-server)
- [The common shape](#the-common-shape)
- [Comparison across four harnesses](#comparison-across-four-harnesses)
- [The portability shortcut: shared directories](#the-portability-shortcut-shared-directories)
- [Build one end to end](#build-one-end-to-end)
- [Porting to OpenCode](#porting-to-opencode)
- [Porting to Roo Code](#porting-to-roo-code)
- [What doesn't travel](#what-doesnt-travel)
- [Security: an agent is a wider grant than a skill](#security-an-agent-is-a-wider-grant-than-a-skill)
- [Sources](#sources)

## Where an agent sits next to a skill and an MCP server

An agentic setup is usually layered:

| Layer | Mechanism | Answers | Loads |
| --- | --- | --- | --- |
| Ambient project context | `AGENTS.md` / `CLAUDE.md` | *"How do we build, test, and code here?"* | Always |
| Invokable procedures | Skills / Cursor rules | *"How do we do this specific task?"* | On demand |
| Live actions & data | MCP servers | *"What can the agent actually call?"* | On call |

An **agent template** is the layer above those three: it doesn't add
knowledge (a skill) or actions (MCP) by itself — it packages a *persona* that
gets handed a scoped slice of both, plus a system prompt narrowing its
judgment to one job, and runs as a delegate the parent conversation dispatches
work to and gets a final answer back from. Use one when the task is not just
"which steps do I follow" (a skill) but "who should even be doing this, with
what tools, and what should the parent hear back" — a focused code reviewer,
a read-only researcher, a background test-runner.

## The common shape

Every harness here represents an agent template the same underlying way, even
though the file format and field names differ:

- **Identity** — a short, stable name the harness and the parent model refer
  to it by.
- **Description / when-to-use** — the router. The only thing read for an
  agent that isn't currently active, so it decides whether the agent ever
  gets used.
- **Role / system prompt** — the body. What the delegate is told about its
  job once invoked.
- **Tool access** — some notion of restricting what the delegate can do,
  at varying granularity.

Model choice and fine-grained tool permissions are *not* part of that common
shape — they vary enough across harnesses that treating them as portable will
mislead you (see [What doesn't travel](#what-doesnt-travel)).

## Comparison across four harnesses

| | **Claude Code** | **Cursor** | **OpenCode** | **Roo Code** |
| --- | --- | --- | --- | --- |
| File | one `.md` per agent | one `.md` per agent | one `.md` per agent | one entry in a shared `.roomodes` |
| Location | `.claude/agents/` (project), `~/.claude/agents/` (user) | `.cursor/agents/` (project), `~/.cursor/agents/` (user) — also reads `.claude/agents/` and `.codex/agents/` directly | `.opencode/agents/` (project), `~/.config/opencode/agents/` (user) | `.roomodes` (project root), `custom_modes.yaml` (global) |
| Identity field | `name:` | `name:` (or filename) | filename (no field) | `slug:` + a separate display `name:` |
| Router field | `description:` | `description:` | `description:` (required) | `description:` (UI blurb) + `whenToUse:` (routing text) |
| Role / body | Markdown body = system prompt | Markdown body = instructions | Markdown body = system prompt | `roleDefinition:` (+ `customInstructions:`) |
| Tool access | `tools:` allowlist / `disallowedTools:` denylist, by exact tool name | `readonly:` (coarse boolean only, per current docs) | `permission:` object per category (`edit`, `bash`, ... → `allow`\|`ask`\|`deny`) | `groups:` — `read`/`edit`/`command`/`mcp`, `edit` optionally scoped by `fileRegex` |
| Model field | `model:` (alias, full ID, or `inherit`) | `model:` (`inherit`, `fast`, or a model ID) | `model:` (`provider/model-id` form) | not in `.roomodes` — bound per-mode in Roo's own settings UI |
| Invocation | auto-delegated from `description`, or `@agent-name` | auto-delegated, or `@agent-name` | auto-invoked (subagent mode) or `@mention` | explicit mode switch (UI, `/mode`, or an orchestrator) |

## The portability shortcut: shared directories

Before reaching for any conversion, know this: **Cursor reads `.claude/agents/`
and `.codex/agents/` natively.** Its own docs state the precedence rule
outright — *"Project subagents take precedence when names conflict. When
multiple locations contain subagents with the same name, `.cursor/` takes
precedence over `.claude/` or `.codex/`."* In practice this means a single
file saved at `.claude/agents/<name>.md` is already a working agent in **both**
Claude Code and Cursor, with zero translation — Cursor just ignores any
frontmatter key it doesn't recognize (`disallowedTools`, `permissionMode`,
`skills`, `hooks`, and the rest of the Claude-Code-only fields listed in the
[example template](agent_template/example-agent.md)).

That's two of the four harnesses covered by writing the file once. OpenCode
and Roo Code each need a real (if small) translation step, covered below.

## Build one end to end

Here's the whole arc on a small, real agent: a **changelog drafter** that
turns a range of git commits into a user-facing changelog entry and writes
it to `CHANGELOG.md`. It's a good first agent to build because it's
genuinely useful and needs no network access or external service to test —
any git repo with a few commits in it works, including this one.

### Step 1 — Write the file

Run this from wherever you'll launch `claude` from — Claude Code discovers
`.claude/agents/` relative to the session's launch directory, whether that's
your repo root or a subdirectory, so it doesn't have to be the repo root:

```bash
mkdir -p .claude/agents
```

`.claude/agents/changelog-drafter.md`:

````markdown
---
name: changelog-drafter
description: Drafts a user-facing changelog entry from a range of git commits, and writes it to CHANGELOG.md on request. Use when the user asks for release notes, a changelog entry, or wants to summarize what changed between two commits or tags for an audience outside the team.
model: inherit
tools: Read, Grep, Glob, Bash, Write, Edit
---

You are a changelog drafter. You turn a raw range of git commits into a
short, user-facing changelog entry — the kind that ships in a CHANGELOG.md
or a release announcement, not a commit-log dump — and write it to
`CHANGELOG.md` when asked to.

## When you're invoked

You're handed a commit range (a tag range, a SHA range, or "since my last
release") and asked for a changelog entry, or someone describes what shipped
in plain language and wants it written up for readers outside the team.

## How you work

1. Run `git log --oneline <range>` to see the commits in range. If no range
   is given, ask for one rather than guessing — never summarize the whole
   history by default.
2. For any commit whose one-line summary doesn't make the user-facing impact
   obvious, run `git show <sha> --stat` (or the full diff) to find out what
   actually changed.
3. Group entries under `### Added`, `### Changed`, `### Fixed`, or
   `### Removed`, using Conventional Commits prefixes (`feat`, `fix`, ...)
   where present, and the actual change where they aren't.
4. Drop internal-only commits — typo fixes, CI tweaks, dependency bumps with
   no visible effect. A changelog is for the reader, not an audit trail. If
   every commit in range is internal-only, say so instead of inventing
   user-facing entries.
5. If asked to write the entry to `CHANGELOG.md`: read the file first if it
   exists, and add the new section above the existing entries rather than
   overwriting them. If the file doesn't exist, create it with a top-level
   `# Changelog` heading.

## What you report back

When just drafting: a short Markdown list under one or more of the headings
above — one line per entry, phrased for someone who doesn't read diffs, no
commit hashes, no internal file paths, no "refactor" or "bump" language.
When asked to write it: the same content, plus confirmation of what file you
wrote and where the new section landed.
````

`tools:` includes `Write` and `Edit` here on purpose — this agent's actual
job is to produce a changelog file, not just draft text for someone else to
paste in, so it needs them.

### Step 2 — Run it against real history

Take this repository's own commits as the worked example:

```bash
git log --oneline -4
```
```
3321a0e Added skills tutorial
8ca333f Updated Base README.md with details on the 2 skills, removed note on how to spin up local ollama model in auth tutorial
bc70e1b Added 2 skills for mcp (server) scaffolding and mcp auth addition
ffd4e01 Initial commit: adding tutorials for mcp and auth
```

Now start (or switch to) a Claude Code session in this repo — run `claude` in
your terminal if one isn't already running, and if this is the first agent
file you've added, restart the session so it picks up `.claude/agents/`.
**`@mentions` are typed at the Claude Code chat prompt, not in your shell** —
pasting one into a terminal instead gives a `command not found` error, since
your shell has no idea what `@changelog-drafter` is. At the chat prompt,
invoke the agent directly, so you're testing the role and tool access rather
than the router:

```
@changelog-drafter draft a changelog entry for ffd4e01..3321a0e
```

Applying the agent's own workflow to those four commits by hand shows what a
correct answer looks like — `bc70e1b` and `3321a0e` are visible additions,
`8ca333f` is a docs correction with no shippable behavior change, and
`ffd4e01` is the initial scaffolding a changelog wouldn't mention at all:

```markdown
### Added
- MCP server auth: OAuth 2.1 authentication and per-tool role checks, with a local Keycloak setup for development.
- MCP server scaffolding: generate a complete, runnable MCP server project from a description.
- A guide to writing agent skills, comparing how Claude, Cursor, and Codex each support them.
```

That's the shape a correct run should produce — three grouped, reader-facing
lines, the doc-typo commit silently dropped rather than translated into a
confusing changelog entry.

### Step 3 — Have it write the file

At the chat prompt, in the same session:

```
@changelog-drafter write that changelog entry to CHANGELOG.md
```

`CHANGELOG.md` should now exist (or gain a new section, on a later run) with
the `# Changelog` heading and the same grouped entries from Step 2:

```markdown
# Changelog

## ffd4e01..3321a0e — 2026-08-27

### Added
- MCP server auth: OAuth 2.1 authentication and per-tool role checks, with a local Keycloak setup for development.
- MCP server scaffolding: generate a complete, runnable MCP server project from a description.
- A guide to writing agent skills, comparing how Claude, Cursor, and Codex each support them.
```

That's the payoff of granting `Write`/`Edit` deliberately in Step 1: the
agent goes from drafting text you'd copy-paste yourself to actually
producing the file.

### Step 4 — Confirm the router, then the portability payoff

- Without `@mention`, just ask in plain language: *"what should go in the
  changelog for the last few commits?"* — confirm Claude reaches for
  `changelog-drafter` on its own. If it doesn't, the `description` needs
  more concrete trigger phrases, not a longer explanation of what a
  changelog is.
- Open the same project in Cursor and confirm the agent shows up there too,
  completely unmodified — the payoff from the shared-directory shortcut
  above.

## Porting to OpenCode

Copy the file to `.opencode/agents/<name>.md` and adjust by hand — small
enough not to need a script:

- Add `mode: subagent` (or `primary`/`all` if it should also be selectable as
  a main session, the way Claude Code's `--agent` flag works).
- Convert `model:` to the `provider/model-id` form OpenCode expects, e.g.
  `anthropic/claude-sonnet-4-6`, rather than the bare alias Claude Code and
  Cursor accept.
- Convert `tools:`/`disallowedTools:` into a `permission:` object keyed by
  category (`edit`, `bash`, ...) with `allow`/`ask`/`deny` values — OpenCode's
  granularity is per-category, not per-tool-name, so a `tools: Read, Grep,
  Bash` allowlist becomes roughly `permission: {edit: deny, bash: allow}`.

## Porting to Roo Code

Roo Code doesn't read one-file-per-agent directories — every custom mode is an
entry in a single `.roomodes` YAML file at the project root. That structural
difference is worth a script rather than hand-editing, since you're merging
into a shared file instead of dropping in a standalone one:

```bash
pip install pyyaml   # the script's only dependency
python 5_agent_templates/agent_template/scripts/to_roomodes.py \
  .claude/agents/your-agent-name.md
```

It upserts (by `slug`) a `customModes` entry into `.roomodes`, mapping
`name` → `slug` + a humanized `name`, `description` → `description` (first
sentence) + `whenToUse` (the full text), the body's first paragraph →
`roleDefinition`, the rest of the body → `customInstructions`, and `tools` →
Roo's coarser `groups` (`read`/`edit`/`command`/`mcp`). **Review the mapped
`groups` and the split role text before committing** — the tools → groups
step is a widening translation (Roo has no per-tool-name allowlist), not an
exact one, and the paragraph split is a heuristic. Roo has no `model` field in
`.roomodes` at all, so the script doesn't try to set one — bind the model for
this mode in Roo's own settings UI.

## What doesn't travel

- **Tool-permission granularity.** Claude Code and Cursor's `tools:`
  allowlists name exact tools; OpenCode and Roo Code only offer coarser
  categories. Going from fine-grained to coarse is always a widening — the
  ported agent can do strictly more than the original, so re-check it, don't
  assume it's equivalent.
- **Model field format and presence.** Bare alias (Claude Code, Cursor) vs.
  `provider/model-id` (OpenCode) vs. not stored in the file at all (Roo Code).
- **Claude-Code-only frontmatter** — `permissionMode`, `skills`, `hooks`,
  `mcpServers`, `effort`, `isolation`, `background`, `initialPrompt` — is
  silently ignored by the other three. Harmless to keep in the canonical
  file; just don't rely on it doing anything once ported.
- **Invocation semantics.** Claude Code and OpenCode both auto-delegate from
  the `description` as the primary path, with `@mention` as the explicit
  override. Roo Code's mode switch is more often a deliberate action (by a
  person or an orchestrating mode) than a silent auto-delegation — write the
  `description`/`whenToUse` text expecting a reader to act on it, not
  assuming a model will route to it unprompted.

## Security: an agent is a wider grant than a skill

An agent template can direct the agent to run code, and it does so with a
standing slice of tool access — often broader than any single task-scoped
instruction — and, in Claude Code, can pre-load MCP servers and skills of its
own. Install and run agent templates only from sources you trust, and before
using a third-party one, audit the frontmatter (what tools/MCP servers
does it actually get?) as carefully as the body.

---

## Sources

**Claude Code — subagents**
- [Create custom subagents (Claude Code docs)](https://code.claude.com/docs/en/sub-agents)

**Cursor — subagents & modes**
- [Subagents (Cursor docs)](https://cursor.com/docs/subagents)
- [Modes (Cursor docs)](https://cursor.com/docs/agent/modes)

**OpenCode — agents**
- [Agents (OpenCode docs)](https://opencode.ai/docs/agents)

**Roo Code — custom modes**
- [Customizing Modes (Roo Code docs)](https://docs.roocode.com/features/custom-modes)
