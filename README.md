# incubationSep2026

This repository contains 4 tutorials and 1 skills folder:

## [1_mcp_tutorial](1_mcp_tutorial/)

Building an MCP server from scratch. Walks through the `mcp` v2 SDK
(`MCPServer`, tools/resources/prompts, stdio vs. Streamable HTTP transports),
using an image-editing server as the running example, then wires it to an
agent that picks which tools to call.

- [writing-an-mcp-server.md](1_mcp_tutorial/writing-an-mcp-server.md) — the full walkthrough
- [mcp_template.py](1_mcp_tutorial/mcp_template.py) — copy-and-fill starter template for a new server

## [2_auth_tutorial](2_auth_tutorial/)

Adding OAuth 2.1 identity to an MCP server. Sets up Keycloak-issued tokens,
a resource server that verifies them (authentication) and enforces
role/scope checks per tool (authorization), and two agents with different
privilege levels calling it — first as plain scripts, then as an LLM
deciding which tool to call.

- [authenticating-and-authorizing-agents.md](2_auth_tutorial/authenticating-and-authorizing-agents.md) — the full walkthrough

## [3_mcp_skills](3_mcp_skills/)

Claude Code skills that automate the two tutorials above. Symlinked into
`.claude/skills/` so Claude Code can discover and invoke them directly.

- [mcp-server-scaffold](3_mcp_skills/mcp-server-scaffold/) — scaffold a complete, runnable MCP server project on the `mcp` Python SDK v2
- [mcp-server-auth](3_mcp_skills/mcp-server-auth/) — add OAuth 2.1 authentication and per-tool role authorization to an existing MCP server project

## [4_skills_tutorial](4_skills_tutorial/)

How to write the skills themselves. Deep-dives the progressive-disclosure model
behind agent skills (metadata → instructions → bundled resources), the `SKILL.md`
frontmatter and description that drive discovery, and the authoring best
practices — conciseness, degrees of freedom, workflows/feedback loops, scripts,
testing and iteration. Then compares the three ecosystems that converged on the
idea — Anthropic Agent Skills, Cursor rules, and OpenAI Codex `AGENTS.md` — so
guidance travels across agents. Sourced from the current Claude, Cursor, and
Codex docs (August 2026).

- [writing-skills-for-agents.md](4_skills_tutorial/writing-skills-for-agents.md) — the full walkthrough
- [skill_template/](4_skills_tutorial/skill_template/) — copy-and-fill starter: annotated `SKILL.md`, a reference stub, and a script stub

## [5_agent_templates](5_agent_templates/)

Defining agent templates — named specialists (role, system prompt, scoped tool
access) that get delegated to rather than loaded into the main conversation.
Builds one real agent end to end (a changelog drafter that reads git history
and writes `CHANGELOG.md`), then compares how four harnesses — Claude Code,
Cursor, OpenCode, and Roo Code — each read that idea, including a shortcut
where a single file already works unmodified in two of them, and a script
that ports it into the one harness structured differently enough to need it.

- [defining-agent-templates.md](5_agent_templates/defining-agent-templates.md) — the full walkthrough
- [agent_template/](5_agent_templates/agent_template/) — copy-and-fill starter: annotated agent `.md`, plus a script to port it into Roo Code's `.roomodes`

