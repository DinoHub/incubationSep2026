# DocTools

An MCP server built on the `mcp` Python SDK v2, served over Streamable HTTP in
Docker, with an in-process test script.

## What is here

| File | What it does |
| --- | --- |
| `doc_tools_server.py` | The server and its tools. This is the file you edit. |
| `http_server.py` | Serves the same server object over Streamable HTTP. |
| `auth.py` | Verifies bearer tokens and checks per-tool roles. |
| `healthcheck.py` | Container healthcheck; confirms the metadata endpoint answers. |
| `test_server.py` | Talks to the server in memory. Checks roles, not tokens. |
| `test_auth.py` | Talks to the running server over HTTP with real tokens. |
| `keycloak/realm-export.json` | The dev realm: roles, client identities, logins. |
| `.env.example` | How to point this at a real OIDC provider. |
| `seed_data.py` | Puts starting data in `documents/`. |
| `requirements.txt` | Python dependencies. |
| `Dockerfile` | Python 3.12 slim, non-root user. |
| `docker-compose.yaml` | The server, Keycloak, and two profile-gated test services. |

## Getting it running

```bash
docker compose build
docker compose run --rm mcp-server python seed_data.py
docker compose run --rm test            # in-process check, no server needed
docker compose --profile dev up -d      # serves http://localhost:8000/mcp
docker compose run --rm test-auth       # tokens over HTTP, against the running server
```

The `dev` profile starts Keycloak alongside the server. Without it the server
comes up with nowhere to verify tokens against, retries discovery for about
thirty seconds, and exits. Use a plain `docker compose up` only once
`OIDC_ISSUER` in `.env` points at a real provider.

## Connecting Claude to it

### Over HTTP, against the container

The server requires a token, so a bare URL no longer connects — it gets an
HTTP 401. Do not paste one in as a header: an access token lasts five minutes
and a pasted one cannot renew itself. Sign in instead, and the host renews on
its own.

```bash
docker compose --profile dev up -d          # the server and its issuer

claude mcp add --transport http --scope user \
  --client-id claude-code --callback-port 8123 \
  doc-tools http://localhost:8000/mcp

claude mcp login doc-tools                  # browser sign-in
claude mcp list                             # look for: doc-tools ... Connected
```

`--client-id` is not optional here. Without it, a host tries Dynamic Client
Registration — it registers itself with the issuer on the fly — and Keycloak
refuses with `Policy 'Trusted Hosts' rejected request to client-registration
service`. Relaxing that policy would not help either: Keycloak's `Full Scope
Disabled` policy strips realm roles from any client registered that way, so
sign-in would succeed and then every tool call would fail with an empty role
list. Naming the pre-registered client avoids both.

Sign in as `dev-writer` (password `dev-writer-password`) for a connection that
may write, or `dev-reader` (`dev-reader-password`) for a read-only one. The
role comes from the login, so which account you use is what decides what the
connection may do.

`--callback-port 8123` has to match one of the redirect URIs registered for the
`claude-code` client in `keycloak/realm-export.json`; any other port is refused
with `Invalid parameter: redirect_uri`. See [Staying connected: refresh
tokens](#staying-connected-refresh-tokens) for what happens when the session
finally expires.

### Over stdio, without the container

A host that launches servers as a subprocess needs no container and no port.
Give it absolute paths — the host does not run the command from this directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
claude mcp add doc-tools -- "$PWD/.venv/bin/python" "$PWD/doc_tools_server.py"
```

stdio is the default transport, which is why this needs no `--transport` flag.

**This route no longer works now that the server has auth, and that is not a
configuration problem.** Tokens are verified by HTTP middleware, and stdio has
no HTTP layer to carry an `Authorization` header, so nothing ever sets a caller
identity. The tools still list, and every call comes back:

```
Error executing tool list_files: This tool requires the 'documents:read' role,
but the caller is not authenticated. Connect with a bearer token.
```

The module also builds its auth settings at import, so `OIDC_ISSUER` has to be
set for it to start at all. Use the HTTP route above.

### Claude Desktop

Desktop registers a URL like this one through **Settings → Connectors → Add
custom connector**, rather than through the CLI above.

### A note on the open port

The port is authenticated: anything without a valid bearer token gets an HTTP
401 during the handshake, before a tool is reachable. What is still
development-grade is everything around it — Keycloak runs over plain HTTP with
a fixed admin password, the token audience is unchecked, and the dev
credentials are committed to this repository. See [What is deliberately not
covered](#what-is-deliberately-not-covered).

## Quick reference

| Task | Command |
| --- | --- |
| Build the image | `docker compose build` |
| Seed the working directory | `docker compose run --rm mcp-server python seed_data.py` |
| Serve over HTTP | `docker compose --profile dev up -d` (server + local issuer) |
| Test in-process | `docker compose run --rm test` |
| Serve over stdio | `python doc_tools_server.py` |
| Test the auth boundary | `docker compose run --rm test-auth` |
| Register with Claude Code | `claude mcp add --transport http --client-id claude-code --callback-port 8123 doc-tools http://localhost:8000/mcp` |
| Sign in (needed once per session) | `claude mcp login doc-tools` |
| Check it connected | `claude mcp list` |
| Sign out | `claude mcp logout doc-tools` |
| Unregister | `claude mcp remove doc-tools` |
| Stop everything | `docker compose down` |

## Authentication and authorization

Every caller needs a bearer token signed by the configured OIDC issuer, and
each tool separately requires a role:

| Role | Tools it unlocks |
| --- | --- |
| `documents:read` | `list_files`, `file_info`, `read_file`, `search_files` |
| `documents:write` | `write_file` (both `overwrite` and `append`) |

The two failures look different, and the difference is not cosmetic. An MCP
connection begins with a handshake before any tool is reachable, so a missing or
invalid token is refused right there with a real **HTTP 401** — no tool code
runs. A caller who *is* authenticated but lacks a tool's role gets a normal
session and then a **tool result marked as an error**, naming the role it was
missing. There is no per-tool HTTP status in MCP.

### Running it locally

The `dev` profile brings up a Keycloak with the realm, roles, and two client
identities already defined, so this needs no configuration:

```bash
docker compose --profile dev up -d        # Keycloak + the server
docker compose run --rm test-auth          # activates its own profile
```

Keycloak's admin console is at `http://localhost:8080/admin`
(`admin` / `admin`). The realm is defined in `keycloak/realm-export.json` and
imported on boot, so the identity setup is a reviewable file rather than a
sequence of clicks someone has to remember.

The realm holds two kinds of identity, because two different things connect to
this server.

**Machine identities**, for scripts, CI, and the tests. They authenticate as
themselves with a secret, using the Client Credentials grant:

| Identity | Client ID | Secret | Roles |
| --- | --- | --- | --- |
| Read-only | `agent-reader` | `reader-dev-secret` | `documents:read` |
| Read-write | `agent-writer` | `writer-dev-secret` | `documents:read`, `documents:write` |

**Human logins**, for an MCP host that signs a person in. The host uses the
public client `claude-code` and gets a token pair; the roles come from the
person, not from the host:

| Login | Password | Roles |
| --- | --- | --- |
| `dev-reader` | `dev-reader-password` | `documents:read` |
| `dev-writer` | `dev-writer-password` | `documents:read`, `documents:write` |

Those secrets are development credentials committed to the repo on purpose, so
the stack runs from a clean checkout. They are not a template for real ones.

Two identities rather than one client that picks a role at request time: if a
single credential could ask for either privilege, holding it *is* holding both,
and the secret becomes the whole boundary. Separate identities are what make a
leaked read-only credential merely embarrassing.

### Staying connected: refresh tokens

Access tokens last five minutes. That is deliberate, and it is not something
you work around by making them last longer — it is what the refresh token is
for. A host signs in once, receives an access token and a refresh token, and
when the access token lapses it quietly trades the refresh token for a new one.
Nobody pastes anything.

Two consequences worth being clear about:

- **Do not register this server with a static `Authorization` header.** A pasted
  bearer token cannot renew itself, so the connection dies after five minutes
  and stays dead. A host that sees a header also stops there: Claude Code
  reports the connection as failed rather than falling back to signing in.
- **Sign in instead.** Add the server with no header and complete the OAuth flow
  from the host. The refresh token is stored with the connection and renewed
  automatically.

```bash
docker compose --profile dev up -d

# No --header. The 401 tells the host where to sign in; --client-id names the
# public client in the realm, and --callback-port matches its redirect URI.
claude mcp add --transport http --scope user \
  --client-id claude-code --callback-port 8123 \
  doc-tools http://localhost:8000/mcp

claude mcp login doc-tools      # opens a browser; sign in as dev-writer
claude mcp list                       # look for: Connected
```

Both flags are required. Leaving out `--client-id` makes the host attempt
Dynamic Client Registration, which Keycloak refuses — see [Over HTTP, against
the container](#over-http-against-the-container) for why relaxing that is not
the fix.

Sign in as `dev-reader` instead to get a connection that can read but not
write. The role is carried by the person who signed in, so which login you use
is what decides the privilege — not which host asked.

Signing in again later, after the session finally expires, is
`claude mcp login doc-tools`. `claude mcp logout doc-tools` discards
the stored tokens.

#### When there is no browser

CI and headless runs cannot complete an interactive sign-in. Two options:

- Use a machine identity and let the host mint a token per connection with a
  `headersHelper`, which Claude Code re-runs on every connect and again after a
  401. That is a re-mint rather than a refresh, and it needs the client secret
  on the machine:

  ```json
  {
    "mcpServers": {
      "doc-tools": {
        "type": "http",
        "url": "http://localhost:8000/mcp",
        "headersHelper": "<absolute path to a script printing {\"Authorization\": \"Bearer <token>\"}>"
      }
    }
  }
  ```

- Or sign in once on a machine that has a browser and copy the stored
  credentials, accepting that they expire with the session.

### Pointing it at a real provider

Copy `.env.example` to `.env` and set `OIDC_ISSUER` to your provider, then start
without the `dev` profile:

```bash
docker compose up -d
```

Set `OIDC_AUDIENCE` too. Without it, any token your issuer signed is accepted —
including one minted for a different service entirely. `OIDC_ROLES_CLAIM` needs
to match where your provider puts roles; the defaults for the common ones are
listed in `.env.example`.

### Testing it

Two tests, and they cover different things:

```bash
docker compose run --rm test                        # in-process: roles, fast
docker compose run --rm test-auth                   # over HTTP: tokens, real
```

`test_server.py` sets the auth context directly, so it checks every tool's role
wiring in about a second without Keycloak. It cannot check authentication at
all — it never crosses the HTTP boundary where tokens are verified. `test_auth.py`
is what proves the verifier works and that an unsigned caller gets a 401.

### The issuer URL has to be reachable from both sides

Keycloak is pinned to `http://localhost:8080` (`KC_HOSTNAME` in
`docker-compose.yaml`), and that URL is what appears in every token's `iss`
claim and in the metadata document this server publishes. It has to be spelled
that way because a host signing in runs on your machine, outside Docker, and
cannot resolve a service name.

The server container has the opposite problem — it cannot resolve `localhost`
to Keycloak — so it fetches signing keys through `OIDC_JWKS_URL`, which points
at `keycloak:8080` on the Docker network. Both halves are set in
`docker-compose.yaml`. Against a real provider neither applies: one public URL
works from everywhere, so leave `OIDC_JWKS_URL` unset.

Getting this wrong produces a 401 that looks exactly like a broken verifier,
which is why `test_auth.py` asserts on what the metadata document advertises.

### What is deliberately not covered

Token audience is unset by default, and the bundled Keycloak runs in
`start-dev` mode over plain HTTP with a fixed admin password. That is a
development identity provider, not a deployment.

The `claude-code` client also has the password grant enabled, which hands
a client the user's password directly — the thing the authorization-code flow
exists to avoid. It is on for one reason: it lets `test_auth.py` obtain a real
refresh token without driving a browser. Turn it off
(`directAccessGrantsEnabled: false` in `keycloak/realm-export.json`) in any
realm that matters, and accept that the refresh checks then need a browser.
