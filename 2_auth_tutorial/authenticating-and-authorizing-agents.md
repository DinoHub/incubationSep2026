# Authenticating and Authorizing Agents

This guide stands up a real OAuth 2.1 identity for an agent, an **MCP server**
that verifies that identity, and two agents with different privilege levels
calling it — first as plain scripts, then as an LLM deciding for itself which
tool to call from a natural-language request, so you can see the same
authorization boundary hold up against a model instead of just a script.

The resource server follows the [MCP authorization tutorial](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/authorization#python)'s
Python approach — `MCPServer` with a `token_verifier` and `AuthSettings` — but
verifies tokens with a locally-cached signing key instead of calling
Keycloak's introspection endpoint on every request; both are legitimate, and
the tutorial explains the trade-off in Step 2.

The setup was run against **Keycloak 26.0**, **`mcp` 2.1.0**, and **PyJWT
2.13** (current stable lines as of August 2026) before being written down.

## Authentication vs. authorization, for an agent specifically

These two words get blurred together, but the resource server checks them in
that order, for different reasons:

- **Authentication (authN): who is calling?** The tool server needs to know
  it's really `agent-writer` and not something pretending to be it. This is
  what a signed token proves.
- **Authorization (authZ): is that caller allowed to do *this*?** Knowing it's
  really `agent-writer` doesn't mean `agent-writer` can delete anything it
  wants. This is a role, scope, or policy check against the caller's identity.

The two failures look different at the wire level, because of *when* each one
happens. An MCP connection starts with a handshake before any tool is ever
called; authentication is checked right there, so a missing or invalid token
gets a real **401 Unauthorized** — the connection itself is refused. A role
check, by contrast, only makes sense once a specific tool is being called
*inside* an already-authenticated session — so a caller who's genuinely who
they say they are, but lacks the role a tool requires, doesn't get a
different HTTP status; they get back a **tool call result marked as an
error**, with a message explaining what role was missing. You'll see both in
Step 5.

The agent-specific part: an agent is a piece of software acting largely on its
own, often calling other services with no human present to type in a
password. It needs its **own** credential — not the developer's login,
not a shared API key copy-pasted into three services. Two clean ways to give
it one:

- **Client Credentials grant** — the agent authenticates as *itself*, using a
  client ID and secret it holds. This is what this tutorial builds: a
  fixed, standing identity for a backend agent or service.
- **Delegated / on-behalf-of** — the agent acts *for a specific user*, using a
  token that traces back to that user's own login (Authorization Code +
  PKCE, then optionally Token Exchange, RFC 8693, to mint a narrower token for
  each downstream call). See "Where to go from here."

## What you're building

- **Keycloak** as the authorization server: it owns a realm, issues signed
  JSON Web Tokens (JWTs), and holds two OAuth **clients** — `agent-reader` and
  `agent-writer` — each a separate machine identity with its own secret and
  its own roles.
- **A resource server** (`tool-server`) — a real MCP server, built on the
  Python SDK's `MCPServer` — that verifies every connection's bearer token
  against Keycloak's public signing key, then checks the token's roles before
  running each tool call. It gets Protected Resource Metadata (RFC 9728) and
  the `401` + `WWW-Authenticate` challenge for free from the SDK; only the
  per-tool role check is something this tutorial adds.
- **Two agents**, same code, different credentials — one holds only
  `tools:read`, the other holds `tools:read` and `tools:write` — to make the
  authorization boundary concrete rather than theoretical.
- **An LLM-driven variant of both agents** (Step 7) that takes a plain-English
  request instead of a CLI argument and discovers the server's tools for
  itself, via a model served locally through Ollama — so the same
  authorization failure you see from a scripted call is something you can
  also watch a model run into and report back on its own.

```
 agent-reader ──┐                          ┌── verifies signature + issuer (401 if bad)
 agent-writer ──┼─► tool-server (8010)     ┤   checks realm role per tool call (error if missing)
                │   MCPServer + Streamable │
                │   HTTP, /mcp             └── tool result: ok / error
                └─► Keycloak (8080) ── issues + signs the JWT
                    realm: agents
                    clients: agent-reader (tools:read)
                             agent-writer (tools:read, tools:write)
```

## Prerequisites

- **Docker** with Compose (Docker Desktop, or Docker Engine + the compose
  plugin).
- **No external accounts or API keys.** Keycloak runs locally in a container
  and is its own authority — nothing leaves your machine.

You'll create nine files: the realm definition, the resource server, a
scripted agent client, an LLM-driven agent, a healthcheck, a test script,
`requirements.txt`, a `Dockerfile`, and `docker-compose.yaml`.

---

## Step 1 — Define the realm: two agents, two roles

Rather than clicking through Keycloak's admin console, you hand it a realm
definition to import on boot — this makes the whole identity setup
reproducible and reviewable as a file. Create `keycloak/realm-export.json`:

```json
{
  "realm": "agents",
  "enabled": true,
  "accessTokenLifespan": 300,
  "roles": {
    "realm": [
      { "name": "tools:read", "description": "Can list and read tool resources" },
      { "name": "tools:write", "description": "Can create, modify, and delete tool resources" }
    ]
  },
  "clients": [
    {
      "clientId": "agent-reader",
      "name": "Read-only agent",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "secret": "reader-secret",
      "serviceAccountsEnabled": true,
      "standardFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "authorizationServicesEnabled": false
    },
    {
      "clientId": "agent-writer",
      "name": "Read-write agent",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "secret": "writer-secret",
      "serviceAccountsEnabled": true,
      "standardFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "authorizationServicesEnabled": false
    }
  ],
  "users": [
    {
      "username": "service-account-agent-reader",
      "enabled": true,
      "serviceAccountClientId": "agent-reader",
      "realmRoles": ["tools:read"]
    },
    {
      "username": "service-account-agent-writer",
      "enabled": true,
      "serviceAccountClientId": "agent-writer",
      "realmRoles": ["tools:read", "tools:write"]
    }
  ]
}
```

A few things worth understanding, not just copying:

- **`serviceAccountsEnabled: true`, `standardFlowEnabled: false`, `directAccessGrantsEnabled: false`.**
  This is what makes each client a pure machine identity: no login page
  (`standardFlow`), no username/password grant (`directAccessGrants`) —
  only the Client Credentials grant, which is exactly the "the agent
  authenticates as itself" pattern.
- **The roles live on the service account user, not the client.** Keycloak
  auto-creates a hidden user (`service-account-<clientId>`) for every
  service-account-enabled client; that user is what actually holds roles.
  This is also why `agent-writer` lists both roles: it's not "inheriting"
  from `agent-reader`, each grant is independent — a second, separate role
  assignment that happens to be a superset.
- **Two clients, not one client with a "role" parameter the agent picks.** If
  one client could request either role, holding the credential *is* holding
  both permissions — the client secret becomes the only boundary, and
  leaking it leaks everything. Separate identities per privilege level is
  what makes a leaked `agent-reader` secret merely embarrassing instead of
  catastrophic.
- **`accessTokenLifespan: 300`** — tokens expire in 5 minutes. Short-lived
  tokens are the main defense against a leaked one being useful for long; an
  agent that needs longer just asks for a new token, which costs one HTTP
  call.

## Step 2 — Write the resource server

The tool server never sees a client secret. It only ever sees a bearer token,
and it verifies that token cryptographically against Keycloak's published
public key — the same trust model as checking a signature, not a password.
Create `tool_server.py`:

```python
import os
from pathlib import Path

import jwt
from jwt import PyJWKClient
from pydantic import AnyHttpUrl, BaseModel

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

# The only exception type whose message reaches the caller. Anything else is
# re-raised as UnexpectedToolError with the text replaced by a bare "Error
# executing tool <name>" — which would silently gut every denial below.
from mcp.server.mcpserver.exceptions import ToolError

# Where the agents' files live. Confining every path to one folder is what
# stops an authenticated-but-misbehaving agent from touching anything else.
FILES_DIR = Path(os.environ.get("FILES_DIR", "files")).resolve()
FILES_DIR.mkdir(parents=True, exist_ok=True)

ISSUER = os.environ["KEYCLOAK_ISSUER"]  # e.g. http://keycloak:8080/realms/agents
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8010")
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
_jwk_client = PyJWKClient(JWKS_URL)


# ---- AuthN: is this a real, unexpired token signed by our Keycloak? -------

class JWKSTokenVerifier(TokenVerifier):
    """Verifies a Keycloak-issued JWT locally against the realm's published
    signing key. The MCP spec's own tutorial verifies tokens via Keycloak's
    introspection endpoint instead — also a valid choice, but it requires
    registering this server as its own confidential Keycloak client and
    costs a network round trip per call. A self-contained signed JWT like
    Keycloak's doesn't need that: checking the signature against a cached
    public key is enough, the same trust model `tool_server.py` used before
    this file became an MCP server."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = _jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=ISSUER,
                # No audience mapper is configured on the realm, so there's
                # no "aud" claim to check here. See the tutorial's "Where to
                # go from here" section for why that matters in production.
                options={"verify_aud": False},
            )
        except jwt.PyJWTError:
            return None
        roles = claims.get("realm_access", {}).get("roles", [])
        return AccessToken(
            token=token,
            client_id=claims.get("azp", "unknown"),
            scopes=roles,  # this token's Keycloak realm roles, treated as its MCP scopes
            expires_at=claims.get("exp"),
            subject=claims.get("preferred_username", claims.get("sub")),
            claims=claims,
        )


mcp = MCPServer(
    "Agent Tool Server",
    instructions=(
        "Tools for reading and writing files in a shared folder. Every tool "
        "requires an authenticated caller; list_files and read_file also "
        "require the 'tools:read' role, write_file and delete_file require "
        "'tools:write'."
    ),
    token_verifier=JWKSTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(ISSUER),
        resource_server_url=AnyHttpUrl(SERVER_URL),
        # No server-wide scope requirement: any authenticated agent may call
        # the server at all. Which *tools* it can actually run is checked
        # per call below — the MCP spec's own "Common Pitfalls" section
        # calls this out explicitly: "verify required scopes per route/tool
        # on the resource server," not with one catch-all scope.
        required_scopes=[],
    ),
)


# ---- AuthZ: does this identity's token carry the role this tool needs? ----

def _require_role(role: str) -> AccessToken:
    """MCPServer has already rejected any request with no valid token before
    a tool ever runs — that's the 401 case. This is the other case: a real,
    verified identity that simply doesn't have the role this tool needs."""
    token = get_access_token()
    if token is None or role not in token.scopes:
        who = token.subject if token else "unknown"
        roles = token.scopes if token else []
        raise ToolError(f"'{who}' has roles {roles}, but this action needs '{role}'.")
    return token


def _resolve(name: str) -> Path:
    p = (FILES_DIR / name).resolve()
    if p.parent != FILES_DIR:
        raise ToolError(f"{name!r} is outside the files directory.")
    return p


class WriteResult(BaseModel):
    name: str
    bytes_written: int


# ---- Tools --------------------------------------------------------------

@mcp.tool()
def list_files() -> list[str]:
    """List the files available on the tool server. Requires the 'tools:read' role."""
    _require_role("tools:read")
    return sorted(p.name for p in FILES_DIR.iterdir() if p.is_file() and not p.name.startswith("."))


@mcp.tool()
def read_file(name: str) -> str:
    """Read the text content of a file by name. Requires the 'tools:read' role."""
    _require_role("tools:read")
    p = _resolve(name)
    if not p.exists():
        raise ToolError(f"No such file: {name!r}")
    return p.read_text()


@mcp.tool()
def write_file(name: str, content: str) -> WriteResult:
    """Create or overwrite a file with the given text content. Requires the 'tools:write' role."""
    _require_role("tools:write")
    p = _resolve(name)
    p.write_text(content)
    return WriteResult(name=name, bytes_written=len(content))


@mcp.tool()
def delete_file(name: str) -> dict:
    """Delete a file by name. Requires the 'tools:write' role."""
    _require_role("tools:write")
    p = _resolve(name)
    if not p.exists():
        raise ToolError(f"No such file: {name!r}")
    p.unlink()
    return {"deleted": name}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
```

Four details worth calling out:

- **`MCPServer(token_verifier=..., auth=AuthSettings(...))` is doing more than
  it looks like.** Passing those two arguments is what makes the SDK publish
  the Protected Resource Metadata document, answer an unauthenticated request
  with `401` plus a `WWW-Authenticate` header pointing back at that document,
  and hand every bearer token it *does* receive to `JWKSTokenVerifier.verify_token`
  before a tool ever runs. None of that is code you write yourself — see
  Step 5 for what it looks like on the wire.
- **`get_access_token()` is how a tool sees who's calling.** It reads a
  context variable the SDK sets for the duration of the request, so it works
  from inside any tool without threading a token through every function
  signature — the same way `mcp_tutorial`'s tools never had to know about
  transport, just about images.
- **The denial is a `ToolError`, and the type is load-bearing.** Raising is
  how a tool hands the model (or script) a readable reason to react to instead
  of a stack trace, and it's also *how* authorization failures surface here —
  there's no per-tool HTTP status in MCP, only a JSON-RPC result marked
  `is_error`. But only `ToolError` keeps your message: the SDK re-raises
  anything else as `UnexpectedToolError` and replaces the text with a bare
  `Error executing tool write_file`. Swap the `ToolError` in `_require_role`
  for a `ValueError` and every denial in this tutorial still *happens* —
  `is_error` is still true, nothing crashes, nothing warns — while the caller
  stops being told which role it was missing. That's the difference between a
  boundary an agent can recover from and one it can only bounce off.
- **`required_scopes=[]` at the server level, real checks inside each tool.**
  The official tutorial's example server requires the same scope for both of
  its tools, so it never needs finer granularity. This one has two roles and
  four tools split across them, so the check has to happen per tool — which
  is also what the MCP spec's own security guidance recommends over one
  catch-all scope.

## Step 3 — Write the agent, and the container files

The agent authenticates once per run — trading its client ID and secret for
an access token — then attaches that token to the MCP connection itself, as a
plain HTTP header. It never touches Keycloak's signing keys or the resource
server's authorization logic; it only holds a credential and a token. Create
`agent_client.py`:

```python
import asyncio
import os
import sys

import httpx2
import requests

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

TOKEN_URL = os.environ["TOKEN_URL"]
CLIENT_ID = os.environ["AGENT_CLIENT_ID"]
CLIENT_SECRET = os.environ["AGENT_CLIENT_SECRET"]
TOOL_SERVER_URL = os.environ.get("TOOL_SERVER_URL", "http://tool-server:8000/mcp")


def get_token() -> str:
    """Client Credentials grant: the agent authenticates as itself, not as a user."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def show(result) -> None:
    status = "ERROR" if result.is_error else "OK"
    text = "\n".join(b.text for b in result.content if getattr(b, "type", None) == "text")
    print(f"  -> {status} {text}")


async def run(action: str, args: list[str]) -> None:
    token = get_token()
    print(f"Authenticated as {CLIENT_ID!r}.")

    # The bearer token travels as a plain HTTP header, same as it would for
    # any other API — MCP's auth layer sits on top of Streamable HTTP, it
    # doesn't invent its own credential transport.
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    transport = streamable_http_client(TOOL_SERVER_URL, http_client=http_client)

    async with Client(transport) as client:
        if action == "tools":
            listing = await client.list_tools()
            for t in listing.tools:
                print(f"  - {t.name}: {t.description}")
        elif action == "list":
            show(await client.call_tool("list_files", {}))
        elif action == "read":
            show(await client.call_tool("read_file", {"name": args[0]}))
        elif action == "write":
            show(await client.call_tool("write_file", {"name": args[0], "content": args[1]}))
        elif action == "delete":
            show(await client.call_tool("delete_file", {"name": args[0]}))
        else:
            print(f"Unknown action: {action!r}. Use one of: tools, list, read, write, delete.")
            sys.exit(1)


if __name__ == "__main__":
    args = sys.argv[1:]
    action = args[0] if args else "tools"
    asyncio.run(run(action, args[1:]))
```

`streamable_http_client(url, http_client=...)` accepts a pre-configured HTTP
client — `httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})` —
which is where the token actually attaches to the connection. Everything
after that (`list_tools`, `call_tool`) is the same `mcp.Client` API
`mcp_tutorial` used against an in-memory server; the only thing that changed
is what's on the other end of the transport.

`healthcheck.py` — the Protected Resource Metadata document is the one MCP
endpoint reachable without a token, so it doubles as a liveness check,
stdlib only:

```python
import os
import sys
import urllib.request

port = os.environ.get("PORT", "8000")
try:
    urllib.request.urlopen(f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource", timeout=3)
except OSError:
    sys.exit(1)
```

`requirements.txt` — `openai` is only used by the LLM-driven agent from Step
7, not by the resource server or the scripted client, but it's cheap to
install once now:

```
mcp>=2,<3
pydantic>=2
pyjwt[crypto]>=2.9
httpx2>=2
requests>=2.32
openai>=1.40      # only needed by agent_llm.py, not the server
```

`Dockerfile` — the app runs as a non-root user; note the pre-existing `files/`
directory this depends on, explained below. It also copies `agent_llm.py`,
which you'll write in Step 7 — copying it now means one image serves every
step in this tutorial:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tool_server.py agent_client.py agent_llm.py test_auth.py healthcheck.py ./

RUN useradd --create-home appuser && mkdir -p /app/files && chown appuser /app/files
USER appuser

EXPOSE 8000
CMD ["python", "tool_server.py"]
```

(If you'd rather write `agent_llm.py` when you get to Step 7, just create an
empty file with that name for now — the `COPY` needs it to exist, but nothing
runs it until then.)

## Step 4 — Compose the whole stack

One file brings up the authorization server, the resource server, and both
agent identities. Create `docker-compose.yaml`:

```yaml
services:
  # Authorization server. Issues and signs tokens; owns the realm, the
  # clients (one per agent identity), and the roles those clients hold.
  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    command: ["start-dev", "--import-realm"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: admin
    volumes:
      - ./keycloak:/opt/keycloak/data/import
    ports:
      - "8080:8080"          # host:container — admin console at /admin
    healthcheck:
      # No curl/wget in this image; a bare TCP connect is enough, since the
      # port only opens once the realm import above has finished.
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/8080"]
      interval: 5s
      timeout: 3s
      retries: 20
      start_period: 20s

  # Resource server. An MCP server that verifies bearer tokens against
  # Keycloak's public keys and enforces per-tool roles — it never sees a
  # client secret.
  tool-server:
    build: .
    image: agent-tool-server:latest
    depends_on:
      keycloak:
        condition: service_healthy
    environment:
      KEYCLOAK_ISSUER: http://keycloak:8080/realms/agents
      # SERVER_URL isn't set — tool_server.py's default ("http://localhost:8010")
      # already matches the host-published port. It's only used to fill in
      # the Protected Resource Metadata document (see Step 5), not to
      # restrict which hostname agents actually connect through.
    ports:
      - "8010:8000"          # host:container — 8010 to avoid clashing with mcp_tutorial's 8000
    volumes:
      - ./files:/app/files
    healthcheck:
      test: ["CMD", "python", "healthcheck.py"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 5s
    restart: unless-stopped

  # Runs test_auth.py against the two agent identities below, then exits.
  # Profile-gated so a plain `up` doesn't run it.
  test:
    build: .
    image: agent-tool-server:latest
    profiles: ["test"]
    depends_on:
      tool-server:
        condition: service_healthy
    environment:
      TOKEN_URL: http://keycloak:8080/realms/agents/protocol/openid-connect/token
      TOOL_SERVER_URL: http://tool-server:8000/mcp
      READER_SECRET: reader-secret
      WRITER_SECRET: writer-secret
    command: ["python", "test_auth.py"]

  # Two agents, two separate identities, two different privilege levels.
  # Each gets its own client_id/secret in Keycloak — never share credentials
  # across agents, even ones written by the same team.

  agent-reader:
    build: .
    image: agent-tool-server:latest
    profiles: ["agents"]
    depends_on:
      tool-server:
        condition: service_healthy
    environment:
      TOKEN_URL: http://keycloak:8080/realms/agents/protocol/openid-connect/token
      TOOL_SERVER_URL: http://tool-server:8000/mcp
      AGENT_CLIENT_ID: agent-reader
      AGENT_CLIENT_SECRET: reader-secret
    entrypoint: ["python", "agent_client.py"]

  agent-writer:
    build: .
    image: agent-tool-server:latest
    profiles: ["agents"]
    depends_on:
      tool-server:
        condition: service_healthy
    environment:
      TOKEN_URL: http://keycloak:8080/realms/agents/protocol/openid-connect/token
      TOOL_SERVER_URL: http://tool-server:8000/mcp
      AGENT_CLIENT_ID: agent-writer
      AGENT_CLIENT_SECRET: writer-secret
    entrypoint: ["python", "agent_client.py"]

  # --- LLM-driven agents (profile: llm), see Step 7 -----------------------
  # Same two identities, same tool server — but now a model decides which
  # tool to call from a plain-English request, instead of a CLI argument
  # telling it exactly what to do. The authorization boundary doesn't care
  # which one is asking.

  ollama:
    image: ollama/ollama:latest
    profiles: ["llm"]
    ports:
      - "11434:11434"        # host:container
    volumes:
      - ollama-models:/root/.ollama

  agent-llm-reader:
    build: .
    image: agent-tool-server:latest
    profiles: ["llm"]
    depends_on:
      tool-server:
        condition: service_healthy
      ollama:
        condition: service_started
    environment:
      TOKEN_URL: http://keycloak:8080/realms/agents/protocol/openid-connect/token
      TOOL_SERVER_URL: http://tool-server:8000/mcp
      AGENT_CLIENT_ID: agent-reader
      AGENT_CLIENT_SECRET: reader-secret
      OPENAI_BASE_URL: ${OPENAI_BASE_URL:-http://ollama:11434/v1}
      OPENAI_MODEL: ${OPENAI_MODEL:-qwen3:8b}
      OPENAI_API_KEY: "ollama"   # any non-empty string; the local server ignores it
    entrypoint: ["python", "agent_llm.py"]

  agent-llm-writer:
    build: .
    image: agent-tool-server:latest
    profiles: ["llm"]
    depends_on:
      tool-server:
        condition: service_healthy
      ollama:
        condition: service_started
    environment:
      TOKEN_URL: http://keycloak:8080/realms/agents/protocol/openid-connect/token
      TOOL_SERVER_URL: http://tool-server:8000/mcp
      AGENT_CLIENT_ID: agent-writer
      AGENT_CLIENT_SECRET: writer-secret
      OPENAI_BASE_URL: ${OPENAI_BASE_URL:-http://ollama:11434/v1}
      OPENAI_MODEL: ${OPENAI_MODEL:-qwen3:8b}
      OPENAI_API_KEY: "ollama"
    entrypoint: ["python", "agent_llm.py"]

volumes:
  ollama-models:
```

`agent-reader` and `agent-writer` sit behind an `agents` profile, and the
Ollama-backed pieces behind an `llm` profile, so a bare `docker compose up`
starts only the always-on pieces — Keycloak and the tool server — and doesn't
try to run agents or pull a multi-gigabyte model as long-lived services.

Before the first run, create the mounted files directory yourself, owned by
your own user:

```bash
mkdir -p files && touch files/.gitkeep
```

This matters because of *who* writes into it. The container runs as a
non-root `appuser` (UID 1000) for defense in depth — if the tool server were
ever compromised, it can't write outside `/app/files`, let alone touch the
host as root. Docker auto-creates a missing bind-mount directory owned by
**root**, and a non-root container user can't write into that. Pre-creating
`files/` as yourself sidesteps it — on most single-user Linux and macOS
setups your user is UID 1000, matching `appuser` exactly (the same reason
`mcp_tutorial`'s `images/` directory works: it's checked into the repo rather
than created fresh by Docker).

## Step 5 — Build, run, and watch the boundary hold

Build the image, then start Keycloak and the resource server:

```bash
docker compose build
docker compose up -d
```

Wait for both to report healthy (`docker compose ps`), then list the tools as
an authenticated agent — this is a real `list_tools` call over the MCP
connection, not a hand-written summary:

```bash
docker compose --profile agents run --rm agent-reader tools
```

```
Authenticated as 'agent-reader'.
  - list_files: List the files available on the tool server. Requires the 'tools:read' role.
  - read_file: Read the text content of a file by name. Requires the 'tools:read' role.
  - write_file: Create or overwrite a file with the given text content. Requires the 'tools:write' role.
  - delete_file: Delete a file by name. Requires the 'tools:write' role.
```

Now try the read-only agent on something it isn't allowed to do:

```bash
docker compose --profile agents run --rm agent-reader write hello.txt "hi"
```

```
Authenticated as 'agent-reader'.
  -> ERROR Error executing tool write_file: 'service-account-agent-reader' has roles ['tools:read'], but this action needs 'tools:write'.
```

That's the whole point made concrete: `agent-reader` authenticated
successfully — the MCP connection opened fine, Keycloak handed it a
perfectly valid, signed token — and the tool call still came back marked as
an error, because authentication and authorization are two different
questions with two different answers here. The read-write agent, by
contrast, can do all four:

```bash
docker compose --profile agents run --rm agent-writer write hello.txt "hi"
docker compose --profile agents run --rm agent-reader read hello.txt
docker compose --profile agents run --rm agent-reader delete hello.txt   # still ERROR
docker compose --profile agents run --rm agent-writer delete hello.txt   # OK
```

To see the authentication side fail — a real HTTP 401, not a tool-call error
— talk to the endpoint directly, the way any MCP client would before it even
gets to `list_tools`:

```bash
curl -s -i http://localhost:8010/mcp -X POST -H "Content-Type: application/json" -d '{}'
```

```
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://localhost:8010/.well-known/oauth-protected-resource"

{"error": "invalid_token", "error_description": "Authentication required"}
```

That `resource_metadata` URL is the Protected Resource Metadata document
(RFC 9728) — it's how a real MCP client, given nothing but this server's
address, discovers *which* authorization server to talk to. It's reachable
without a token, since a client has to be able to fetch it before it has one:

```bash
curl -s http://localhost:8010/.well-known/oauth-protected-resource
```

```
{"resource":"http://localhost:8010/","authorization_servers":["http://keycloak:8080/realms/agents"],"scopes_supported":[],"bearer_methods_supported":["header"]}
```

Every agent in this tutorial skips that discovery step — it already knows
`TOKEN_URL` from its own environment, because Client Credentials is a
machine-to-machine grant with no browser involved. An interactive client like
VS Code or Claude Desktop, connecting on a human's behalf, is the one that
actually walks this document to find its way to Keycloak. More on that gap in
"Where to go from here."

## Step 6 — Run the automated check

`test_auth.py` exercises the full authN/authZ matrix — no token, a garbage
token, each agent's allowed and disallowed actions — the two ways they fail
are different enough to need two different techniques: authentication is
checked with a raw HTTP request (since the failure happens before an MCP
session ever opens), authorization with a real `mcp.Client` call (since the
failure happens *inside* one).

Each denial is checked twice, on purpose: once that it happened, and once that
its message survived. `is_error` alone cannot tell a useful denial from one
whose text the SDK replaced with `Error executing tool write_file`, and that
failure is silent — see the `ToolError` note in Step 2.

```python
import asyncio
import os

import httpx2
import requests

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

TOKEN_URL = os.environ["TOKEN_URL"]
TOOL_SERVER_URL = os.environ.get("TOOL_SERVER_URL", "http://tool-server:8000/mcp")

CREDS = {
    "agent-reader": os.environ["READER_SECRET"],
    "agent-writer": os.environ["WRITER_SECRET"],
}

failures = 0


def check(label: str, ok: bool) -> None:
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures += 1


def token_for(client_id: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": CREDS[client_id]},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def raw_status(token: str | None) -> int:
    """Hit the MCP endpoint directly over HTTP, bypassing the MCP client SDK.
    Authentication is enforced by MCPServer's ASGI middleware before a
    request ever reaches the JSON-RPC layer, so even a bogus body still gets
    a real 401 at the HTTP level — the same thing `curl` would see."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.post(TOOL_SERVER_URL, json={}, headers=headers)
    return resp.status_code


async def call(token: str, name: str, args: dict):
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    transport = streamable_http_client(TOOL_SERVER_URL, http_client=http_client)
    async with Client(transport) as client:
        return await client.call_tool(name, args)


async def main() -> None:
    reader_token = token_for("agent-reader")
    writer_token = token_for("agent-writer")

    # No token at all -> 401 (not authenticated). MCPServer rejects this
    # before the JSON-RPC layer ever runs.
    check("no token is rejected (401)", raw_status(None) == 401)

    # A garbage token -> also 401.
    check("garbage token is rejected (401)", raw_status("not-a-real-jwt") == 401)

    # From here on the token is valid, so we're inside an authenticated MCP
    # session — authorization failures show up as tool errors, not HTTP
    # status codes, since they happen after the connection is already open.
    r = await call(reader_token, "list_files", {})
    check("reader can list files", not r.is_error)

    r = await call(reader_token, "write_file", {"name": "note.txt", "content": "hello"})
    check("reader cannot write (tool error)", r.is_error)
    # Check the message, not just the flag. If _require_role raised anything
    # other than ToolError, the text collapses to "Error executing tool
    # write_file" — the caller is told it failed and never told why, while an
    # is_error-only check above still passes. That is the exact bug this line
    # exists to catch.
    check("the write denial names the missing role",
          "tools:write" in (r.content[0].text if r.content else ""))

    r = await call(writer_token, "write_file", {"name": "note.txt", "content": "hello from the writer agent"})
    check("writer can write", not r.is_error)

    r = await call(writer_token, "read_file", {"name": "note.txt"})
    check(
        "writer can read its own file (content matches)",
        not r.is_error and r.content[0].text == "hello from the writer agent",
    )

    r = await call(reader_token, "read_file", {"name": "note.txt"})
    check("reader can read the writer's file", not r.is_error)

    r = await call(reader_token, "delete_file", {"name": "note.txt"})
    check("reader cannot delete (tool error)", r.is_error)
    check("the delete denial names the missing role",
          "tools:write" in (r.content[0].text if r.content else ""))

    r = await call(writer_token, "delete_file", {"name": "note.txt"})
    check("writer can delete", not r.is_error)

    print()
    if failures:
        print(f"{failures} check(s) failed.")
        raise SystemExit(1)
    print("All checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
docker compose --profile test run --rm test
```

```
PASS  no token is rejected (401)
PASS  garbage token is rejected (401)
PASS  reader can list files
PASS  reader cannot write (tool error)
PASS  the write denial names the missing role
PASS  writer can write
PASS  writer can read its own file (content matches)
PASS  reader can read the writer's file
PASS  reader cannot delete (tool error)
PASS  the delete denial names the missing role
PASS  writer can delete

All checks passed.
```

That's real output from these exact files.

## Step 7 — Put a model in the loop

Everything so far has been a script deciding what to call — `agent_client.py`
takes `list`, `read`, `write`, or `delete` as a literal CLI argument and does
exactly that. That's authentication and authorization working, but it isn't
yet an *agent* in the sense of something making its own decision about which
tool a request calls for.

`agent_llm.py` is the same shape as `agent_client.py` — get a token, open the
MCP connection with it attached — except after that, a model takes over. It
calls `list_tools()` on the real connection (the exact call `agent_client.py`
made in Step 5) to see what's on offer, then decides for itself what to call,
in what order, reading each result before deciding the next step — the same
tool-use loop as `mcp_tutorial`'s `agent_local.py`. The part worth watching
for: the model never gets to bypass the resource server's role check. It's
just another caller with a bearer token, and if that token's identity lacks
the role, it gets the same tool-call error a script would. Create
`agent_llm.py`:

```python
import asyncio
import json
import os
import sys

import httpx2
import requests
from openai import OpenAI

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

TOKEN_URL = os.environ["TOKEN_URL"]
CLIENT_ID = os.environ["AGENT_CLIENT_ID"]
CLIENT_SECRET = os.environ["AGENT_CLIENT_SECRET"]
TOOL_SERVER_URL = os.environ.get("TOOL_SERVER_URL", "http://tool-server:8000/mcp")

BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://ollama:11434/v1")  # Ollama
MODEL = os.environ.get("OPENAI_MODEL", "qwen3:8b")
API_KEY = os.environ.get("OPENAI_API_KEY", "ollama")  # non-empty; local server ignores it
MAX_STEPS = 8


def get_token() -> str:
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def to_openai_tools(mcp_tools) -> list[dict]:
    """MCP's input_schema is already JSON-schema; wrap it in OpenAI's function
    shape. Same helper as mcp_tutorial's agent_local.py — the model sees
    real tool definitions discovered from the server, not ones hand-written
    for it here."""
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
    token = get_token()
    llm = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    transport = streamable_http_client(TOOL_SERVER_URL, http_client=http_client)

    async with Client(transport) as mcp_client:
        listing = await mcp_client.list_tools()
        tools = to_openai_tools(listing.tools)
        messages: list = [
            {
                "role": "system",
                "content": (
                    f"You are an agent authenticated to the tool server as the Keycloak "
                    f"client '{CLIENT_ID}'. Its access token determines what you're allowed "
                    f"to do, not you. If a tool call fails because this identity's role "
                    f"doesn't permit the action, report that to the user plainly instead of "
                    f"retrying the same call or trying to work around it."
                ),
            },
            {"role": "user", "content": request},
        ]

        for _ in range(MAX_STEPS):
            resp = llm.chat.completions.create(model=MODEL, messages=messages, tools=tools, temperature=0)
            msg = resp.choices[0].message

            if not msg.tool_calls:
                print("\nAgent:", msg.content)
                return msg.content or ""

            messages.append(msg)
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                print(f"  -> {call.function.name}({args})")
                result = await mcp_client.call_tool(call.function.name, args)
                text = text_of(result)
                print(f"     {'ERROR: ' if result.is_error else ''}{text}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": text})

        return "Stopped: hit the step limit."


if __name__ == "__main__":
    request = sys.argv[1] if len(sys.argv) > 1 else "List the files you can see."
    print(f"Authenticated as {CLIENT_ID!r}. Request: {request!r}")
    asyncio.run(run(request))
```

The system prompt is doing real work here: it tells the model what a tool
error in this context *means* (a role the identity doesn't have, not a bug to
route around) — without it, some models will retry the same call a few times
or try a workaround before giving up, which burns steps and looks like the
model "getting confused" when actually the resource server behaved exactly
as designed.

Bring up Ollama and pull a tool-calling model into it — no API key anywhere,
nothing leaves your machine:

```bash
docker compose --profile llm up -d ollama
docker compose exec ollama ollama pull qwen3:8b
```

(As in `mcp_tutorial`: use `exec` against the already-running `ollama`
container, not `run`, which would start a fresh container with no server for
the CLI to talk to. `qwen3:8b` is a solid small default as of mid-2026 —
Apache 2.0, native tool support; check any model you swap in with
`ollama show <model>` for `tools` under Capabilities.)

Now ask the write-capable agent to do something in one sentence, chaining two
tool calls:

```bash
docker compose --profile llm run --rm agent-llm-writer "Write a short note that says 'ocean tutorial demo' to a file called ocean.txt, then read it back to confirm it saved correctly."
```

```
Authenticated as 'agent-writer'. Request: "Write a short note that says 'ocean tutorial demo' to a file called ocean.txt, then read it back to confirm it saved correctly."
  -> write_file({'name': 'ocean.txt', 'content': 'ocean tutorial demo'})
     {
  "name": "ocean.txt",
  "bytes_written": 19
}
  -> read_file({'name': 'ocean.txt'})
     ocean tutorial demo

Agent: The file `ocean.txt` has been successfully written and read back. Here's the confirmation:

**Written content:**
`ocean tutorial demo`

**Bytes written:**
19 (matches the length of the text)

The file contents match exactly, so the operation is complete.
```

Then ask the *read-only* identity to delete that same file:

```bash
docker compose --profile llm run --rm agent-llm-reader "Delete the file ocean.txt."
```

```
Authenticated as 'agent-reader'. Request: 'Delete the file ocean.txt.'
  -> delete_file({'name': 'ocean.txt'})
     ERROR: Error executing tool delete_file: 'service-account-agent-reader' has roles ['tools:read'], but this action needs 'tools:write'.

Agent: The deletion failed because the 'agent-reader' identity only has the 'tools:read' role, but deleting files requires the 'tools:write' role. This action cannot be completed with the current permissions.
```

This is the whole tutorial in one transcript: the model discovered the
server's real tools over an authenticated MCP connection, picked the right
one for a plain-English instruction, and reported the authorization failure
that came back — without the resource server ever needing to know or care
that a model, rather than a script, was the one asking. (Both transcripts
above are real output from these exact files — CPU inference, no GPU.)

## Where to go from here

- **Set and verify an audience (`aud`) claim.** This tutorial's resource
  server skips audience validation (`verify_aud: False`) because the realm
  doesn't set one. In production, add a Keycloak *audience mapper* to each
  client scoping its tokens to `tool-server`, and check it on decode — that's
  what stops a token minted for one resource server from being replayed
  against a different one that trusts the same Keycloak. This is exactly the
  `aud` claim the official MCP authorization tutorial walks through
  configuring in Keycloak's UI.
- **Try the introspection-based `TokenVerifier` instead.** The official
  tutorial's `IntrospectionTokenVerifier` calls Keycloak's RFC 7662 endpoint
  on every request rather than checking a cached signing key locally. That
  costs a network round trip per call, but it's the right tradeoff for
  opaque tokens, or when you need revocation to take effect immediately
  rather than waiting out the token's lifespan.
- **Support real interactive clients, not just Client Credentials.** Every
  agent here already knows `TOKEN_URL` and skips the discovery flow in Step
  5 entirely. A human-facing MCP client (VS Code, Claude Desktop) instead
  walks the Protected Resource Metadata document to find the authorization
  server, then needs Dynamic Client Registration and a full Authorization
  Code + PKCE flow with a consent screen — Keycloak supports both out of the
  box, but this tutorial's realm never exercises them because none of its
  clients are `standardFlowEnabled`.
- **Delegated auth: agents acting *for* a user.** Client Credentials gives an
  agent its own standing identity. When it should act with a specific
  human's permissions instead, look at Authorization Code + PKCE for the
  user's initial login, then **Token Exchange (RFC 8693)** to have the agent
  trade that token for a narrower one scoped to each downstream call — so a
  multi-step agent doesn't hold one broad token capable of everything it
  might ever touch.
- **Rotate secrets, don't hardcode them.** `reader-secret` and
  `writer-secret` are plaintext in a realm-export file for this tutorial.
  Keycloak can generate secrets at creation time; keep the generated value in
  a secret manager (Vault, cloud KMS, or at minimum `.env` files never
  committed) and rotate it on a schedule or on suspected compromise.
- **Use short-lived tokens plus refresh, not long-lived ones.** `300` seconds
  here is already short by convention; resist the temptation to raise it "to
  avoid extra requests" — an agent making a lot of calls should re-fetch a
  token, not hold one long enough to matter if it leaks.
- **Scope roles to the smallest useful unit.** `tools:read` / `tools:write`
  is coarse. A production agent fleet often wants per-tool or per-resource
  roles (`files:read`, `files:delete`, `orders:refund`) so that compromising
  one agent's credential exposes only what that agent actually needed.
- **Read the source of truth.** MCP's own authorization tutorial:
  `https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/authorization`.
  Authorization specification: `https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization`.
  Keycloak docs: `https://www.keycloak.org/documentation`. Token Exchange:
  `https://www.rfc-editor.org/rfc/rfc8693`.

## Quick reference

| Task | Command |
| --- | --- |
| Create the mounted files dir | `mkdir -p files && touch files/.gitkeep` |
| Build the image | `docker compose build` |
| Start Keycloak + the tool server | `docker compose up -d` |
| Check both are healthy | `docker compose ps` |
| Run the automated authN/authZ checks | `docker compose --profile test run --rm test` |
| List tools as an agent | `docker compose --profile agents run --rm agent-reader tools` |
| Read-only agent tries to write (expect a tool error) | `docker compose --profile agents run --rm agent-reader write x.txt "hi"` |
| Read-write agent writes (expect OK) | `docker compose --profile agents run --rm agent-writer write x.txt "hi"` |
| See a real 401 (no MCP session ever opens) | `curl -i http://localhost:8010/mcp -X POST -d '{}'` |
| Fetch the Protected Resource Metadata doc | `curl http://localhost:8010/.well-known/oauth-protected-resource` |
| Serve the local model | `docker compose --profile llm up -d ollama` |
| Pull a tool-capable model | `docker compose exec ollama ollama pull qwen3:8b` |
| Ask the LLM-driven writer agent | `docker compose --profile llm run --rm agent-llm-writer "your request"` |
| Ask the LLM-driven reader agent | `docker compose --profile llm run --rm agent-llm-reader "your request"` |
| Keycloak admin console | `http://localhost:8080/admin` (admin / admin) |
| Stop everything | `docker compose down` |
