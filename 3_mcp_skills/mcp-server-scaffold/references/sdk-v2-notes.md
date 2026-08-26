# mcp Python SDK v2 — the parts that cost time

Verified against `mcp` 2.1.0. Most MCP material online still shows v1, so a
copied example will often fail in one of the ways below.

## Contents

- [Only ToolError reaches the model](#only-toolerror-reaches-the-model)
- [v1 vs v2 imports](#v1-vs-v2-imports)
- [Transports and where their arguments go](#transports-and-where-their-arguments-go)
- [Reading a tool call result](#reading-a-tool-call-result)
- [Testing in process](#testing-in-process)
- [Container details that bite](#container-details-that-bite)

## Only ToolError reaches the model

This is the costliest surprise in v2, because it fails silently. A tool that
raises anything other than `ToolError` has its message discarded:
`mcp/server/mcpserver/tools/base.py` catches the exception and re-raises it as
`UnexpectedToolError(f"Error executing tool {name}")`. The call is still marked
`is_error`, the server stays up, and nothing warns you — the model simply gets
no reason for the failure.

```python
from mcp.server.mcpserver.exceptions import ToolError
```

That import path is the only one that works. `ToolError` is not re-exported from
`mcp`, `mcp.server`, or `mcp.server.mcpserver` (whereas `MCPServer` is available
from both `mcp.server` and `mcp.server.mcpserver`).

Observed behaviour, same tool, two exception types:

| Raised | `is_error` | What the caller sees |
| --- | --- | --- |
| `ValueError("No such file: 'x'. Call list_files.")` | `True` | `Error executing tool read_file` |
| `ToolError("No such file: 'x'. Call list_files.")` | `True` | `Error executing tool read_file: No such file: 'x'. Call list_files.` |

So: `ToolError` for anticipated failures the model should read and recover from,
and let genuine bugs propagate and be wrapped, which keeps internals out of the
model's context. Test for it by asserting on the message text, not just
`is_error`.

## v1 vs v2 imports

The high-level server class was renamed. The decorators did not change.

```python
from mcp.server import MCPServer          # v2 (current)
# from mcp.server.fastmcp import FastMCP  # v1 — this module no longer exists
```

An `ImportError` on `mcp.server.fastmcp`, or a `NameError` on `FastMCP`, means
you are looking at a v1 example. Swap the import and the constructor call;
`@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()` work the same.

## Transports and where their arguments go

Two transports matter:

- **stdio** for local servers the host launches as a subprocess. This is the
  default, so `mcp.run()` with no arguments is stdio.
- **Streamable HTTP** for anything reachable over a network, which includes
  anything in a container — stdio does not cross a container boundary.

In v2, transport and networking arguments live on `run()`, not on the
`MCPServer` constructor. Passing `host` or `port` to the constructor is a common
v1 habit that fails here.

```python
mcp = MCPServer("MyServer", instructions="...")        # no transport args here
mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

Bind `0.0.0.0` in a container. Binding `127.0.0.1` makes the server unreachable
from outside even with the port mapped, which looks like a networking bug and is
not one.

The HTTP endpoint is `/mcp` — so `http://localhost:8000/mcp`, not the bare root.

## Reading a tool call result

`call_tool` returns an object with three fields worth knowing:

```python
r = await client.call_tool("read_file", {"name": "notes.txt"})
r.structured_content   # parsed dict — see below
r.content[0].text      # the text block; where an error message lands
r.is_error             # True when the tool raised
```

`structured_content` is populated for plain return types too, not only for
`BaseModel` returns — a tool annotated `-> str` returning `"ok"` gives
`{"result": "ok"}`, with the bare value in `content[0].text`. So a test can read
`structured_content` for either kind of tool, as long as it expects the
`result` wrapper around scalars.

A failed call is *not* an exception on the client side. It comes back with
`is_error` set and the message in `content`, which is what lets a model read the
failure and retry. Two ways a test goes wrong here: expecting a raise (it will
never come, so the test passes while the tool is broken), and asserting only on
`is_error` (which cannot distinguish a good error message from a swallowed one —
see the `ToolError` section above).

`list_tools()` returns a listing object, not a list. The tools are on `.tools`,
and each has `.name`, `.description`, and `.input_schema`:

```python
listing = await client.list_tools()
names = [t.name for t in listing.tools]
```

## Testing in process

`Client` accepts the server object directly, which runs both sides in one
process — no subprocess, no network, no port.

```python
import asyncio
from mcp import Client
from my_server import mcp

async def main():
    async with Client(mcp) as client:
        ...

asyncio.run(main())
```

This is the fastest way to check a server, and it works with the container
stopped. Test the HTTP path separately only when you are debugging transport or
deployment, not tool logic.

## Container details that bite

- **The healthcheck cannot be an HTTP GET.** `/mcp` rejects any plain GET,
  because the endpoint requires MCP's own headers and session handling — and it
  does so with different status codes depending on what you send: 406 with no
  `Accept` header, 400 with `Accept: */*` (which is what curl sends by default).
  Do not key a healthcheck to either number. Checking that the port accepts a
  TCP connection is the honest check, and it needs no dependencies.
- **Copy every runnable file in before the first build.** The test script is run
  by a compose service from the same image, so a missing `COPY` surfaces later as
  a confusing "no such file" at `docker compose run` time.
- **The served port has no authentication.** Streamable HTTP on a mapped port is
  fine on localhost and not fine on a public interface. Put it behind OAuth 2.1
  before exposing it.

## Sources of truth

- Python SDK docs: https://modelcontextprotocol.github.io/python-sdk/
- Protocol spec: https://modelcontextprotocol.io
- SDK repo: https://github.com/modelcontextprotocol/python-sdk
