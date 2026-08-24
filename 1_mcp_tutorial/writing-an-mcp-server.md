# Writing an MCP Server and Agent

This guide builds an image-editing MCP server (crop, blur, resize, etc.),
runs it in Docker, tests it, and wires it to a small **agent** that lets a model
decide which tools to call.

The server code was run against **`mcp` 2.0.0** (the current stable line as of
August 2026) before being written down.

## What an MCP server actually is

MCP is an open standard for connecting AI models to external capabilities. The
common analogy is a USB-C port for AI: instead of writing a bespoke integration
for every model–tool pair, you write one server, and any MCP-compatible host
(Claude Desktop, Cursor, VS Code, your own agent) can use it.

A server exposes three kinds of things, called *primitives*:

- **Tools** — actions the model can invoke (crop an image, call an API, run a query).
- **Resources** — read-only context the host can load (a file, a config, a record).
- **Prompts** — reusable, parameterized message templates the user can trigger.

The host connects over a *transport*: **stdio** for local servers (the server
runs as a subprocess), or **Streamable HTTP** for remote ones. In a container we
use Streamable HTTP, because stdio isn't reachable across the container boundary.

## A note before you start: v1 vs v2

The Python SDK had a major rework in v2, and this trips people up because most
tutorials online still show v1. The change you'll hit immediately:

```python
from mcp.server import MCPServer          # v2 (current)
# from mcp.server.fastmcp import FastMCP  # v1 (old — import no longer exists)
```

The high-level class was renamed from `FastMCP` to `MCPServer`. The decorators
(`@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`) work the same way. If you
copy a v1 example and get an `ImportError` on `fastmcp`, this is why.

## Prerequisites

- **Docker** with Compose (Docker Desktop, or Docker Engine + the compose plugin).
- **No API key required.** The server is served over HTTP on a plain port
  (`http://localhost:8000/mcp` — see Step 5), and the agent in Step 7 talks to
  a model you serve locally via Ollama, also over a plain port
  (`http://localhost:11434`) — nothing leaves your machine.

You'll create nine files: the server, a sample-image helper, an HTTP entrypoint,
a healthcheck, `requirements.txt`, a `Dockerfile`, `docker-compose.yaml`, a test
script, and an agent. Put them all in one folder.

---

## Step 1 — Write the server

The tools all edit files inside one working directory. Confining every path to a
single folder is what stops a model from reading or writing arbitrary files —
worth building in from the start.

Create `image_server.py`:

```python
import os
from pathlib import Path

from PIL import Image, ImageFilter
from pydantic import BaseModel

from mcp.server import MCPServer

# The one directory every tool is allowed to touch.
IMAGE_DIR = Path(os.environ.get("IMAGE_DIR", "images")).resolve()
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

mcp = MCPServer(
    "ImageTools",
    instructions=(
        "Tools for editing images in a shared folder. Call list_images to see "
        "what's available and image_info to check dimensions before cropping."
    ),
)


class ImageResult(BaseModel):
    """What every editing tool returns."""

    output: str  # filename of the new image, within the image directory
    width: int
    height: int


class ImageInfo(BaseModel):
    name: str
    width: int
    height: int
    format: str
    mode: str


def _resolve(name: str) -> Path:
    """Resolve a name to a path, refusing anything outside IMAGE_DIR."""
    p = (IMAGE_DIR / name).resolve()
    if p.parent != IMAGE_DIR:
        raise ValueError(f"{name!r} is outside the image directory.")
    return p


def _open(name: str) -> Image.Image:
    p = _resolve(name)
    if not p.exists():
        raise ValueError(f"No such image: {name!r}. Call list_images to see what's there.")
    return Image.open(p)


def _default_output(name: str, suffix: str) -> str:
    """Turn 'cat.png' + 'blur' into 'cat_blur.png'."""
    stem, _, ext = name.rpartition(".")
    ext = ext or "png"
    return f"{stem or name}_{suffix}.{ext}"


def _save(img: Image.Image, output: str) -> ImageResult:
    out_path = _resolve(output)
    img.save(out_path)
    return ImageResult(output=output, width=img.width, height=img.height)


# ---- Read-only tools ------------------------------------------------------

@mcp.tool()
def list_images() -> list[str]:
    """List the images available in the working directory."""
    exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
    return sorted(p.name for p in IMAGE_DIR.iterdir() if p.suffix.lower() in exts)


@mcp.tool()
def image_info(name: str) -> ImageInfo:
    """Get the dimensions and format of an image."""
    img = _open(name)
    return ImageInfo(
        name=name, width=img.width, height=img.height,
        format=img.format or "unknown", mode=img.mode,
    )


# ---- Editing tools --------------------------------------------------------

@mcp.tool()
def crop(name: str, left: int, top: int, right: int, bottom: int, output: str | None = None) -> ImageResult:
    """Crop an image to the box (left, top, right, bottom) in pixels."""
    img = _open(name)
    if right <= left or bottom <= top:
        raise ValueError("Need right > left and bottom > top.")
    return _save(img.crop((left, top, right, bottom)), output or _default_output(name, "crop"))


@mcp.tool()
def blur(name: str, radius: float = 2.0, output: str | None = None) -> ImageResult:
    """Apply a Gaussian blur. Larger radius = blurrier."""
    img = _open(name)
    return _save(img.filter(ImageFilter.GaussianBlur(radius=radius)), output or _default_output(name, "blur"))


@mcp.tool()
def resize(name: str, width: int, height: int, output: str | None = None) -> ImageResult:
    """Resize an image to an exact width and height in pixels."""
    img = _open(name)
    if width < 1 or height < 1:
        raise ValueError("Width and height must be positive.")
    return _save(img.resize((width, height)), output or _default_output(name, "resized"))


@mcp.tool()
def grayscale(name: str, output: str | None = None) -> ImageResult:
    """Convert an image to grayscale."""
    return _save(_open(name).convert("L"), output or _default_output(name, "gray"))


@mcp.tool()
def rotate(name: str, degrees: float, output: str | None = None) -> ImageResult:
    """Rotate an image counter-clockwise by a number of degrees."""
    return _save(_open(name).rotate(degrees, expand=True), output or _default_output(name, "rot"))


if __name__ == "__main__":
    mcp.run()  # stdio by default
```

The things you did **not** write are the point. There's no JSON Schema: the type
hints (`left: int`, `radius: float = 2.0`) *are* the schema, and the SDK
generates it. No request parsing, no serialization, no protocol handling.

Three details worth calling out:

- **Docstrings matter.** The model reads a tool's docstring to decide when to
  call it. "Apply a Gaussian blur. Larger radius = blurrier." tells it both what
  the tool does and how the parameter behaves. Vague docstrings mislead it.
- **Return a typed object for structured output.** Returning `ImageResult`
  gives the host a schema and structured content it can parse, not just text.
- **Raise to signal a problem.** A raised exception comes back to the model as a
  readable error it can react to — here, by fixing its crop box and retrying.

A sample image to edit, `create_sample.py`:

```python
import os
from pathlib import Path
from PIL import Image, ImageDraw

IMAGE_DIR = Path(os.environ.get("IMAGE_DIR", "images")).resolve()
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

img = Image.new("RGB", (400, 300), "#4a90d9")
draw = ImageDraw.Draw(img)
draw.ellipse([120, 90, 280, 210], fill="#f5a623")
draw.rectangle([40, 40, 120, 120], fill="#7ed321")

out = IMAGE_DIR / "sample.png"
img.save(out)
print(f"Created {out} ({img.width}x{img.height})")
```

## Step 2 — Add the container files

`http_server.py` serves the same `mcp` object over Streamable HTTP, bound to
`0.0.0.0` so it's reachable once the port is mapped:

```python
import os
from image_server import mcp

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # In v2, transport + networking options live on run(), not the constructor.
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
```

`healthcheck.py` — a plain GET to `/mcp` returns 406 (the endpoint needs MCP's
own headers), so the check just confirms the port is open. Stdlib only:

```python
import os, socket, sys

port = int(os.environ.get("PORT", "8000"))
try:
    socket.create_connection(("127.0.0.1", port), timeout=3).close()
except OSError:
    sys.exit(1)
```

`requirements.txt`:

```
mcp>=2,<3
Pillow>=11
openai>=1.40      # only needed by agent_local.py, not the server
```

`Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY image_server.py http_server.py test_server.py healthcheck.py \
     agent_local.py create_sample.py ./

RUN useradd --create-home appuser && mkdir -p /app/images && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["python", "http_server.py"]
```

`docker-compose.yaml` — the server, a one-shot test, and a `local` profile that
serves an open-weights model with Ollama and drives it with an agent. The
`./images` mount means images on your host are visible to the tools, and
edited files show up back on your host:

```yaml
services:
  mcp-server:
    build: .
    image: mcp-imagetools:latest
    ports:
      - "8000:8000"          # host:container
    environment:
      PORT: "8000"
    volumes:
      - ./images:/app/images
    healthcheck:
      test: ["CMD", "python", "healthcheck.py"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 5s
    restart: unless-stopped

  # Runs the test suite, then exits. Profile-gated so a plain `up` skips it.
  test:
    build: .
    image: mcp-imagetools:latest
    profiles: ["test"]
    volumes:
      - ./images:/app/images
    command: ["python", "test_server.py"]

  # --- Local model stack (profile: local) ---------------------------------
  # Open-weights model via Ollama. No API key, nothing leaves your machine.

  ollama:
    image: ollama/ollama:latest
    profiles: ["local"]
    ports:
      - "11434:11434"        # host:container
    volumes:
      - ollama-models:/root/.ollama

  # The agent. entrypoint is fixed to `python agent_local.py`, so the request
  # text you pass to `docker compose run --rm agent-local "..."` becomes its
  # argument.
  agent-local:
    build: .
    image: mcp-imagetools:latest
    profiles: ["local"]
    depends_on: [ollama]
    environment:
      OPENAI_BASE_URL: ${OPENAI_BASE_URL:-http://ollama:11434/v1}
      OPENAI_MODEL: ${OPENAI_MODEL:-qwen3:8b}
      OPENAI_API_KEY: "ollama"   # any non-empty string; the local server ignores it
    volumes:
      - ./images:/app/images
    entrypoint: ["python", "agent_local.py"]

volumes:
  ollama-models:
```

## Step 3 — Write the test script

`test_server.py` uses v2's `Client` to talk to the server object **in memory** —
no subprocess, no network — so it's a fast, self-contained check. The Dockerfile
from Step 2 already `COPY`s it in, so it needs to exist before the first build:

```python
import asyncio
from mcp import Client
from image_server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print("Tools:", [t.name for t in tools.tools])

        # What's in the folder, and how big is the sample?
        images = await client.call_tool("list_images", {})
        print("Images:", images.structured_content)

        info = await client.call_tool("image_info", {"name": "sample.png"})
        print("sample.png ->", info.structured_content)

        # Run a few edits. Each returns the new filename + dimensions.
        r = await client.call_tool("blur", {"name": "sample.png", "radius": 4})
        print("blur ->", r.structured_content)

        r = await client.call_tool(
            "crop", {"name": "sample.png", "left": 100, "top": 70, "right": 300, "bottom": 230}
        )
        print("crop ->", r.structured_content)

        r = await client.call_tool(
            "resize", {"name": "sample.png", "width": 128, "height": 96, "output": "thumb.png"}
        )
        print("resize ->", r.structured_content)

        r = await client.call_tool("grayscale", {"name": "sample.png"})
        print("grayscale ->", r.structured_content)

        # A bad crop comes back as a readable error, not a crash.
        r = await client.call_tool(
            "crop", {"name": "sample.png", "left": 300, "top": 0, "right": 100, "bottom": 100}
        )
        print("bad crop is_error ->", r.is_error)
        print("bad crop message ->", r.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
```

## Step 4 — Write the agent

Here's the part that makes it an *agent* rather than a script: the model gets
the tool list and decides which tools to call, in what order, to satisfy a
plain request. The agent below never imports Pillow and doesn't know what
"blur" means — it discovers the tools at runtime and forwards calls. Point it
at a different MCP server and it works unchanged.

Nothing about MCP requires a cloud model. The agent loop just needs *some*
model that supports tool calling, and plenty of open-weights models do. The
simplest route is **Ollama**, which runs models locally and exposes an
OpenAI-compatible API — so nothing leaves your machine and there's no key to
manage.

The loop is the standard tool-use pattern: send the request plus the tool list
to the model; if it returns a tool call, run that tool through the MCP client
and feed the result back; repeat until the model answers in plain text. Only
the wire format is specific to OpenAI-compatible servers: tools wrap the
schema in `{"type": "function", ...}`, tool calls come back in
`message.tool_calls` with arguments as a JSON *string*, and you reply with
`role: "tool"` messages. The MCP half is unchanged. Create `agent_local.py` —
the Dockerfile from Step 2 `COPY`s this in too, so, like the test script, it
needs to exist before the first build:

```python
import asyncio
import json
import os
import sys

from openai import OpenAI
from mcp import Client
from image_server import mcp as image_server

BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1")  # Ollama
MODEL = os.environ.get("OPENAI_MODEL", "qwen3:8b")
API_KEY = os.environ.get("OPENAI_API_KEY", "ollama")  # non-empty; local server ignores it
MAX_STEPS = 10


def to_openai_tools(mcp_tools) -> list[dict]:
    """MCP's input_schema is already JSON-schema; wrap it in OpenAI's function shape."""
    return [
        {"type": "function", "function": {
            "name": t.name, "description": t.description or "", "parameters": t.input_schema,
        }}
        for t in mcp_tools
    ]


def text_of(result) -> str:
    parts = [b.text for b in result.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts) if parts else "(no textual output)"


async def run(request: str) -> str:
    llm = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    async with Client(image_server) as mcp_client:
        listing = await mcp_client.list_tools()
        tools = to_openai_tools(listing.tools)
        messages: list = [{"role": "user", "content": request}]

        for _ in range(MAX_STEPS):
            resp = llm.chat.completions.create(
                model=MODEL, messages=messages, tools=tools, temperature=0,
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:                      # done
                print("\nAgent:", msg.content)
                return msg.content or ""

            messages.append(msg)                        # assistant turn w/ tool_calls
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                print(f"  -> {call.function.name}({args})")
                result = await mcp_client.call_tool(call.function.name, args)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": text_of(result)})

        return "Stopped: hit the step limit."


if __name__ == "__main__":
    request = sys.argv[1] if len(sys.argv) > 1 else (
        "Blur sample.png with a large radius, then make a 128x128 grayscale "
        "thumbnail of the original. Tell me the output filenames."
    )
    asyncio.run(run(request))
```

## Step 5 — Build, seed a sample, and run

All nine files exist now, so the image will build cleanly. Build it, create the
sample inside a throwaway container (it lands in `./images` on your host via
the mount), then start the server:

```bash
docker compose build
docker compose run --rm mcp-server python create_sample.py
docker compose up
```

The server is now live at `http://localhost:8000/mcp`. `docker compose up -d`
runs it in the background instead; `docker compose down` stops it.

## Step 6 — Test it

Run the test script from Step 3 in a container (no need for the server to be
up — it runs the server in-process):

```bash
docker compose run --rm test
```

You'll see the tools listed, the edits producing new files in `./images`, and
the bad crop returning `is_error = True` with the message text rather than
crashing. That last part is the intended way to signal a failure the model
should read and recover from.

## Step 7 — Drive it with an agent

The compose file's **`local`** profile (from Step 2) has an `ollama` service and
an `agent-local` service wired to it, running the agent from Step 4. Bring up
Ollama, pull a tool-capable model into it, then run the agent — no key anywhere:

```bash
docker compose --profile local up -d ollama
docker compose exec ollama ollama pull qwen3:8b
docker compose --profile local run --rm agent-local "Blur sample.png with a large radius, then make a 128x128 grayscale thumbnail of the original. Tell me the output filenames."
```

The pull has to go through `exec` (against the already-running `ollama`
container), not `run` (which would start a fresh container with no server for
the CLI to talk to) — and the image's entrypoint is already `ollama`, so a
`run ... ollama ollama pull ...` would double up the command.

The `agent-local` service points at `http://ollama:11434/v1` by default (the
compose service name). If you'd rather use an Ollama you already run **on your
host**, set `OPENAI_BASE_URL=http://host.docker.internal:11434/v1` instead (on
Linux you may also need `extra_hosts: ["host.docker.internal:host-gateway"]`).

A few honest caveats, because local tool calling is less forgiving than a
frontier model:

- **Model choice matters a lot.** Tool-calling reliability varies widely. As of
  mid-2026, `qwen3:8b` is a solid small default (Apache 2.0, native tool
  support); models under ~14B are more prone to malformed calls or loops.
  `qwen3:30b`, `gpt-oss:20b`, or `llama3.3` are steadier if your hardware can
  run them. Check a model supports tools with `ollama show <model>` (look for
  `tools` under Capabilities).
- **The first run is slow.** `ollama pull` downloads several GB, and CPU-only
  inference is sluggish; a GPU helps a lot.
- **Expect more retries.** Small models sometimes botch arguments — which is
  exactly why the tools raise readable errors: the model gets to see what went
  wrong and try again. Clear docstrings and `temperature=0` help.

Because it's just an OpenAI-compatible endpoint, the same `agent_local.py` works
against vLLM, llama.cpp's server, LM Studio, or a hosted OpenAI-compatible
gateway — point `OPENAI_BASE_URL` (and `OPENAI_MODEL`) wherever you like.

## Where to go from here

- **Try a chained multi-tool request.** Give the agent a task that needs three
  tools back to back, and spell out that each step feeds the next:

  ```bash
  docker compose --profile local run --rm agent-local "Blur sample.png with a large radius to create a blurred version, then resize that blurred image to 128x128, then convert that resized image to grayscale."
  ```

  Spelling out "that blurred image" / "that resized image" instead of just
  "blur, resize, and grayscale it" makes it much more likely a smaller local
  model chains each tool's output into the next call's `name` argument
  correctly, rather than re-running every step on the original file (see the
  caveats in Step 7).
- **Return the image itself.** These tools return a filename. MCP also supports
  image content blocks, so a tool can hand the picture back inline — useful when
  the host and server don't share a filesystem.
- **Add authorization.** The HTTP server has no auth — fine on localhost, not on
  a public port. Put it behind OAuth 2.1 before exposing it.
- **Read the source of truth.** Python SDK docs:
  `https://modelcontextprotocol.github.io/python-sdk/`. Protocol spec:
  `https://modelcontextprotocol.io`. SDK repo:
  `https://github.com/modelcontextprotocol/python-sdk`. Anthropic also has a
  free course, *Introduction to Model Context Protocol*.

## Quick reference

| Task | Command |
| --- | --- |
| Build the image | `docker compose build` |
| Make a sample image | `docker compose run --rm mcp-server python create_sample.py` |
| Serve over HTTP | `docker compose up` |
| Test in-process | `docker compose run --rm test` |
| Serve the local model | `docker compose --profile local up -d ollama` |
| Pull a tool-capable model | `docker compose exec ollama ollama pull qwen3:8b` |
| Run the agent | `docker compose --profile local run --rm agent-local "your request"` |
| Stop everything | `docker compose down` |
