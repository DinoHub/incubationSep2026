# CountryInfo

An MCP server that answers factual questions about countries — capital,
population, area, region, currencies, languages, land borders, timezones — from
the [REST Countries API](https://restcountries.com) v5. Built on the `mcp`
Python SDK v2, served over Streamable HTTP in Docker, with an in-process test
script.

## Tools

| Tool | Role | What it does |
| --- | --- | --- |
| `list_countries(region=None)` | `countries:read` | Every country as `Common Name (CODE)`, optionally filtered to one region. Start here when you do not know a country's exact name or code. |
| `get_country(name_or_code)` | `countries:read` | Full detail for one country. Accepts a name or an ISO 3166-1 two- or three-letter code. |
| `search_by_currency(currency_code)` | `countries:search` | The countries using one ISO 4217 currency, e.g. `EUR`. |
| `search_by_language(language)` | `countries:search` | The countries listing one language, by English name (`spanish`) or code (`spa`). |

`get_country` returns `borders` as three-letter codes, so each one can be passed
straight back into `get_country` to walk a country's neighbours.

## What is here

| File | What it does |
| --- | --- |
| `country_info_server.py` | The server and its tools. This is the file you edit. |
| `http_server.py` | Serves the same server object over Streamable HTTP. |
| `auth.py` | Verifies bearer tokens and checks per-tool roles. |
| `healthcheck.py` | Container healthcheck; confirms the metadata endpoint answers. |
| `test_server.py` | Talks to the server in memory. Checks roles, not tokens. |
| `test_auth.py` | Talks to the running server over HTTP with real tokens. |
| `keycloak/realm-export.json` | The dev realm: roles, client identities, logins. |
| `.env.example` | How to point this at a real OIDC provider. |
| `requirements.txt` | Python dependencies. |
| `Dockerfile` | Python 3.12 slim, non-root user. |
| `docker-compose.yaml` | The server, Keycloak, and two profile-gated test services. |

## You need an API key

REST Countries v5 requires one. A free key comes from
<https://restcountries.com/sign-up>; put it in the environment before starting
anything:

```bash
export RESTCOUNTRIES_API_KEY=your_key_here
```

`docker-compose.yaml` passes that variable through to both services, so
exporting it in your shell (or putting it in a `.env` file next to the compose
file) is enough.

With no key set, the server falls back to the demo key the REST Countries docs
publish. That key answers **every** query with the same canned Canada record, so
the tools refuse to answer rather than hand a model fake data: each call comes
back as an error naming `RESTCOUNTRIES_API_KEY`, and the server's `instructions`
say the same thing. The server still starts, the tools still list, and the test
script still passes — it just checks the refusal instead of the data.

The older v3.1 API that wrappers like this used to target has been retired and
now serves only a deprecation notice, so v3.1 paths and field names will not
work here.

## Getting it running

```bash
docker compose build
docker compose run --rm test            # in-process check, no server needed
docker compose --profile dev up -d      # serves http://localhost:8001/mcp
docker compose run --rm test-auth       # tokens over HTTP, against the running server
```

The `dev` profile starts Keycloak alongside the server. Without it the server
comes up with nowhere to verify tokens against, retries discovery for about
thirty seconds, and exits. Use a plain `docker compose up` only once
`OIDC_ISSUER` in `.env` points at a real provider.

The test script runs three groups of checks: tool registration and bad-input
handling always; the demo-key refusals when no key is set; and calls against
real data only when a key is present. It prints which group it took, so a
skipped group cannot be mistaken for a passing one.

## Connecting Claude to it

### Over HTTP, against the container

The server requires a token, so a bare URL no longer connects — it gets an
HTTP 401. Do not paste a token in as a header either: an access token lasts
five minutes and a pasted one cannot renew itself, and a host that sees an
`Authorization` header stops there rather than signing in. Sign in instead,
and the host renews the token on its own.

```bash
docker compose --profile dev up -d

claude mcp add --transport http --scope user \
  --client-id claude-code --callback-port 8124 \
  country-info http://localhost:8001/mcp

claude mcp login country-info
```

Sign in as `dev-writer` (password `dev-writer-password`) for a connection
that may write, or `dev-reader` (`dev-reader-password`) for a read-only
one. `--client-id` is required: without it the host attempts Dynamic Client
Registration, which Keycloak refuses. See [Staying connected: refresh
tokens](#staying-connected-refresh-tokens) for the details.

Then check that it actually answered:

```bash
claude mcp list          # look for: country-info ... Connected
```

`claude mcp add` records the URL whether or not anything is listening, so it
succeeding does not mean the server is reachable — `claude mcp list` is the step
that tells you. If it reports a failure, the container is usually not up.

Inside a session, `/mcp` lists the connected servers, and `claude mcp get
country-info` prints one server's status, scope, and the command to remove it.

`--scope` decides who gets the server:

| Scope | Where it is stored | Who sees it |
| --- | --- | --- |
| `local` (the default) | `~/.claude.json`, keyed to the current directory | You, in this directory only |
| `user` | `~/.claude.json`, not tied to a directory | You, in every directory |
| `project` | `.mcp.json` in the project root | Anyone who checks out the repo |

Use `--scope project` to share it with a team and commit the `.mcp.json` it
writes:

```json
{
  "mcpServers": {
    "country-info": {
      "type": "http",
      "url": "http://localhost:8001/mcp"
    }
  }
}
```

Remove it with `claude mcp remove country-info`, adding `-s project` if you used
project scope.

### Over stdio, without the container

A host that launches servers as a subprocess needs no container and no port.
Give it absolute paths — the host does not run the command from this directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
claude mcp add country-info -- "$PWD/.venv/bin/python" "$PWD/country_info_server.py"
```

stdio is the default transport, which is why this needs no `--transport` flag.

**This route no longer works now that the server has auth, and that is not a
configuration problem.** Tokens are verified by HTTP middleware, and stdio has
no HTTP layer to carry an `Authorization` header, so nothing ever sets a caller
identity. The tools still list, and every call comes back with the tool's role
check refusing an unauthenticated caller. The module also builds its auth
settings at import, so `OIDC_ISSUER` has to be set for it to start at all.
Use the HTTP route above.

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

## Authentication and authorization

Every caller needs a bearer token signed by the configured OIDC issuer, and
each tool separately requires a role:

| Role | Tools it unlocks |
| --- | --- |
| `countries:read` | `list_countries`, `get_country` |
| `countries:search` | `search_by_currency`, `search_by_language` |

Every tool here is read-only, so the split is not read versus write. It is
ordinary versus privileged. Looking one country up is a single upstream request;
the two search tools sweep the whole dataset, cost several paged requests each,
and spend a rate-limited, metered API key — so they are held back behind the
second role. A caller holding only `countries:read` can still answer a currency
or language question the long way, by calling `get_country` on specific
countries and reading their `currencies` and `languages` fields.

Both roles are named in the server's `instructions` and in each tool's
description, so a model that lacks `countries:search` learns that from the tool
listing rather than by trying the call.

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

Keycloak's admin console is at `http://localhost:8081/admin`
(`admin` / `admin`). The realm is defined in `keycloak/realm-export.json` and
imported on boot, so the identity setup is a reviewable file rather than a
sequence of clicks someone has to remember.

The realm holds two kinds of identity, because two different things connect to
this server.

**Machine identities**, for scripts, CI, and the tests. They authenticate as
themselves with a secret, using the Client Credentials grant:

| Identity | Client ID | Secret | Roles |
| --- | --- | --- | --- |
| Lookups only | `agent-reader` | `reader-dev-secret` | `countries:read` |
| Lookups and search | `agent-writer` | `writer-dev-secret` | `countries:read`, `countries:search` |

**Human logins**, for an MCP host that signs a person in. The host uses the
public client `claude-code` and gets a token pair; the roles come from the
person, not from the host:

| Login | Password | Roles |
| --- | --- | --- |
| `dev-reader` | `dev-reader-password` | `countries:read` |
| `dev-writer` | `dev-writer-password` | `countries:read`, `countries:search` |

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
  --client-id claude-code --callback-port 8124 \
  country-info http://localhost:8001/mcp

claude mcp login country-info      # opens a browser; sign in as dev-writer
claude mcp list                       # look for: Connected
```

Both flags are required. Leaving out `--client-id` makes the host attempt
Dynamic Client Registration, which Keycloak refuses — see [Over HTTP, against
the container](#over-http-against-the-container) for why relaxing that is not
the fix.

Sign in as `dev-reader` instead to get a connection that can look countries up
but not run the two search tools. The role is carried by the person who signed
in, so which login you use is what decides the privilege — not which host
asked.

Signing in again later, after the session finally expires, is
`claude mcp login country-info`. `claude mcp logout country-info` discards
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
      "country-info": {
        "type": "http",
        "url": "http://localhost:8001/mcp",
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

Neither test needs a REST Countries API key. Both judge an allowed call by
whether it got past the role check, not by whether it returned data, so a
missing `RESTCOUNTRIES_API_KEY` cannot masquerade as a broken auth boundary.
`test_auth.py` prints a note when a call was allowed and then failed upstream.

### The issuer URL has to be reachable from both sides

Keycloak is pinned to `http://localhost:8081` (`KC_HOSTNAME` in
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

## Quick reference

| Task | Command |
| --- | --- |
| Set the API key | `export RESTCOUNTRIES_API_KEY=...` |
| Build the image | `docker compose build` |
| Serve over HTTP | `docker compose --profile dev up -d` (server + local issuer) |
| Test the auth boundary | `docker compose run --rm test-auth` |
| Test in-process | `docker compose run --rm test` |
| Serve over stdio | `python country_info_server.py` |
| Register with Claude Code | `claude mcp add --transport http --client-id claude-code --callback-port 8124 country-info http://localhost:8001/mcp` |
| Sign in | `claude mcp login country-info` |
| Check it connected | `claude mcp list` |
| Unregister | `claude mcp remove country-info` |
| Stop everything | `docker compose down` |
