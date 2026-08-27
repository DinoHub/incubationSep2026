---
name: mcp-server-scaffold
description: Scaffold a complete, runnable MCP (Model Context Protocol) server project — server module with typed tools, Streamable HTTP entrypoint, container healthcheck, in-process test script, requirements, Dockerfile, and a docker-compose stack — on the mcp Python SDK v2 (MCPServer, not FastMCP). Use this whenever someone wants to build, create, write, start, or set up an MCP server; expose tools, resources, or prompts to a model; wrap an API, a database, a CLI, or a local capability so Claude or another MCP host can call it; containerize or Dockerize an MCP server; or asks for MCP boilerplate, a template, a starter, or a skeleton — even if they never say the word "scaffold". Also use it when someone hits v1-vs-v2 SDK confusion (an ImportError on mcp.server.fastmcp or a missing FastMCP), or wants to add tools to a server this skill generated.
---

# MCP server scaffold

Generate the whole project, then spend your attention on the one file that
actually differs between MCP servers: the tools.

Every generated file but one is boilerplate that is identical across projects
and easy to get subtly wrong — the transport arguments live on `run()` rather
than the constructor, the healthcheck cannot use HTTP because `/mcp` rejects any
plain GET, and the Dockerfile has to copy the test script in before the first
build or compose fails at run time. The script below gets all of that right
every time. What it cannot know is what the server
is *for*, and that is where a scaffold earns or loses its keep: a model decides
whether to call a tool by reading its docstring and signature, so the tools are
the part worth thinking about.

## Workflow

### 1. Settle four things

Ask only about what you cannot infer from the request:

- **Name.** What the model sees, e.g. `ImageTools`. Drives the module name, the
  Docker image tag, and the resource URI scheme.
- **Tools.** What actions the server exposes, and what each one takes and
  returns. If the user gave a domain but no tool list, propose 3-5 tools and
  confirm — that is faster than an interview and gives them something to react to.
- **Whether it owns a directory.** File-handling servers get a single confined
  working directory mounted from the host. API, database, and compute wrappers
  do not; pass `--no-workdir` for those.
- **Extra dependencies.** Anything beyond `mcp` itself, e.g. `Pillow>=11` for
  images or `httpx>=0.27` for an HTTP wrapper.

### 2. Run the scaffold script

```bash
python <skill-dir>/scripts/scaffold.py \
  --name "ImageTools" \
  --dir ./image-tools \
  --workdir images \
  --deps "Pillow>=11"
```

Useful flags: `--no-workdir` for a server with no filesystem, `--module` to
override the module name, `--port` (default 8000), `--force` to overwrite. Run
`--help` for the rest.

The generated project runs as-is — the example tools are real, so
`docker compose run --rm test` passes before you have written a line of domain
logic. That is deliberate: it separates "my environment is broken" from "my
tools are wrong", and those two failures are miserable to debug together.

### 3. Replace the example tools

Edit the server module and nothing else. Read `references/tool-design.md`
before writing the tools — it covers what makes a model call the right tool with
the right arguments, which is the whole game. In short:

- The docstring is the tool description the model reads. Say what the tool does
  *and* how each parameter behaves.
- Type hints are the input schema. The SDK generates JSON Schema from them, so
  never hand-write one.
- Return a `BaseModel` when the caller needs to parse the result; plain types
  are fine for simple tools.
- `raise ToolError` (from `mcp.server.mcpserver.exceptions`) with a message
  saying what to do next. It is the only exception whose text reaches the model
  — a `ValueError` arrives as bare `Error executing tool <name>` with your
  message silently dropped.
- Fill in the `instructions=` string on `MCPServer`. It is the first thing the
  model reads, and it is where ordering constraints belong.

Also update the server `instructions`, the calls in `test_server.py`, and
`seed_data.py` if the project has one. Leaving those pointing at deleted example
tools is the most common way a scaffolded project breaks.

### 4. Verify

```bash
cd <project-dir>
docker compose build
docker compose run --rm test          # in-process; no server needed
```

The test script talks to the server object in memory, so it needs neither a
network nor a running container. Check that every tool appears in the listing,
that each one returns what you expect, and that a deliberately bad call comes
back with `is_error` true **and your message intact**. Asserting only on
`is_error` hides the most common failure here: a tool that raised the wrong
exception type, so the model gets `Error executing tool <name>` and nothing to
act on. The generated test checks the message text for exactly this reason, and
exits non-zero on any failure.

Serve it with `docker compose up` (reachable at `http://localhost:8000/mcp`),
or run `python <name>_server.py` for a host that wants stdio. If Docker is
unavailable, say so and fall back to `pip install -r requirements.txt && python
test_server.py` rather than claiming the container path worked.

### 5. Tell the user how to connect it

A server nobody can reach is not finished. A passing test proves the tools work;
it says nothing about whether Claude can see them, and that is the step people
get stuck on. Close by giving them the actual command, with the port and server
name filled in, not a pointer to the README:

```bash
docker compose up -d                                              # must be running first
claude mcp add --transport http <slug> http://localhost:8000/mcp
claude mcp list                                                   # confirms it connected
```

Two things worth saying out loud, because both cause the same confused report
that "it didn't work":

- `claude mcp add` records the URL whether or not anything is listening. It
  succeeds against a stopped container, and only `claude mcp list` reveals that.
- The default `--scope local` binds the server to the directory it was added
  from. Someone who adds it in one project and then looks for it in another will
  not find it. `--scope user` is usually what people want for a local dev server;
  `--scope project` writes a shareable `.mcp.json`.

The generated README carries the same commands plus the stdio route and the
scope table, so the user is not dependent on this conversation.

## What gets generated

| File | Role |
| --- | --- |
| `<name>_server.py` | The server and its tools. The only file with domain logic. |
| `http_server.py` | Same server object over Streamable HTTP, bound to 0.0.0.0. |
| `healthcheck.py` | Container healthcheck. Stdlib only; checks the port, not HTTP. |
| `test_server.py` | In-process client check. No network, no subprocess. |
| `seed_data.py` | Starting data for the working directory. Omitted with `--no-workdir`. |
| `requirements.txt` | `mcp>=2,<3` plus whatever you passed to `--deps`. |
| `Dockerfile` | Python 3.12 slim, non-root user, port exposed. |
| `docker-compose.yaml` | Server plus a profile-gated `test` service. |
| `README.md` | Build/test/run commands, and how to register the server with Claude. |

## Reference files

- `references/tool-design.md` — writing tools a model uses correctly:
  docstrings, schemas from type hints, structured returns, error handling, and
  confining filesystem access. Read this before writing tools.
- `references/sdk-v2-notes.md` — the SDK v2 API surface and the mistakes that
  cost the most time: `MCPServer` vs `FastMCP`, where transport arguments go,
  the client result shape, and stdio vs Streamable HTTP. Read this when
  something does not import or a result field is not where you expected.

## Adding authentication

The generated server has no auth: anything that can reach the port can call
every tool. The `mcp-server-auth` skill takes a project generated here and adds
a token verifier plus per-tool role checks, so reach for that rather than
hand-rolling it — and mention it when the user talks about exposing the server
beyond localhost.

## Adding to an existing scaffolded project

Do not re-run the script over a project that already has real tools — it
refuses without `--force`, and `--force` would discard the work. Add the new
tool to the server module by hand, extend `test_server.py` with a call for it
plus one bad-input case, and rerun the test.
