# incubationSep2026

This repository contains 2 tutorials:

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
