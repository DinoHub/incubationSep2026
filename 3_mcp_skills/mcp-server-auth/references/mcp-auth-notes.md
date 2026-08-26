# MCP auth on the Python SDK — the parts that cost time

Verified against `mcp` 2.1.0.

## Contents

- [The API surface](#the-api-surface)
- [Where each check happens](#where-each-check-happens)
- [Testing in process, and what it cannot tell you](#testing-in-process-and-what-it-cannot-tell-you)
- [Only ToolError reaches the caller](#only-toolerror-reaches-the-caller)
- [Testing the 401 itself](#testing-the-401-itself)
- [Container and compose details](#container-and-compose-details)

## The API surface

```python
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.middleware.auth_context import get_access_token
```

Wire both arguments on the constructor:

```python
mcp = MCPServer(..., token_verifier=MyVerifier(), auth=AuthSettings(...))
```

`AuthSettings` needs `issuer_url`, `resource_server_url`, and `required_scopes`.
The first two are `pydantic.AnyHttpUrl`, so a bare hostname raises at
construction. `AccessToken` carries `token`, `client_id`, `scopes`,
`expires_at`, `resource`, `subject`, and `claims`.

A `TokenVerifier` returns `AccessToken | None`. Returning `None` is how you
reject — the SDK turns it into a 401. Raising instead leaks a stack trace into
the response path, and gives the caller information about *why* verification
failed, which is not something to volunteer at that edge.

## Where each check happens

Authentication runs in the handshake, before any tool is reachable. Authorization
can only run inside a tool call. That single fact explains most confusion:

| Failure | Shape | Where |
| --- | --- | --- |
| No token, expired, bad signature, wrong issuer | HTTP **401**, connection refused | Handshake |
| Valid token, missing role | Tool result with `is_error` set | Inside the call |

There is no per-tool HTTP status in MCP. A test asserting a 403 on a role denial
will never pass.

## Testing in process, and what it cannot tell you

`Client(mcp)` runs both halves in one process and **skips the auth middleware
entirely** — no 401, no token check. But `get_access_token()` returns `None`, so
every tool calling `require_role()` fails. Adding auth therefore breaks the
scaffold's fast test until you give it an identity.

The auth context is a plain `contextvars.ContextVar`, so a test can set it:

```python
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

auth_context_var.set(AuthenticatedUser(AccessToken(
    token="in-process-test", client_id="test-writer",
    scopes=["tools:read", "tools:write"], expires_at=None, subject="test-writer",
)))
```

`AuthenticatedUser` takes exactly one argument, the `AccessToken`. This is the
same contextvar the real middleware sets from a verified token, so
`require_role()` cannot tell the difference — which is the point, and also why
this belongs only in a test.

The payoff is real: one in-process run checks the allow *and* deny path for every
tool in about a second, with no identity provider running.

The limit is equally real: **this cannot test authentication at all.** The
in-process client never touches the HTTP layer where tokens are verified. A
verifier that accepts every token, or crashes on every token, passes this test.
Only a full-stack test over HTTP covers that.

One consequence worth planning for: importing the server module builds
`AuthSettings`, so *some* issuer value must be present even for the in-process
test. Keep configuration lazy — read the environment inside functions, not at
module scope, and never open a network connection at import time — otherwise the
fast test needs a running identity provider just to import.

## Only ToolError reaches the caller

A role denial is worth nothing if the caller cannot read it. In v2, any exception
other than `ToolError` is re-raised as `UnexpectedToolError` and its message is
replaced with a bare `Error executing tool <name>`:

```python
from mcp.server.mcpserver.exceptions import ToolError  # only path that exports it

raise ToolError(f"{subject!r} has roles {roles}, but this needs {role!r}.")
```

Raise `ValueError` here and the caller is told the call failed and never told
which role it was missing. The failure is silent — `is_error` is still true, the
server does not crash, nothing logs a warning. Assert on the message text, not
just `is_error`.

## Testing the 401 itself

Do not try to read the status code out of the client's exception. The failure
arrives as a nested `ExceptionGroup` whose innermost message is only
`MCPError: Server returned an error response` — no status, nothing separating a
401 from a crash.

Post to the endpoint directly instead:

```python
r = httpx2.post(url, json=INITIALIZE, headers={"Accept": "application/json, text/event-stream"})
assert r.status_code == 401
assert "resource_metadata" in r.headers["www-authenticate"]
```

The observed 401 carries a spec-shaped header:

```
www-authenticate: Bearer error="invalid_token", error_description="Authentication required",
                  resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource"
```

That header is how a compliant client discovers where to get a token, so it is
worth asserting on and not only the bare status.

Note the SDK ships **`httpx2`**, not `httpx`, and does not ship `requests`. A
copied example importing either of those fails on import unless you add it.

## Realm import details

- **The realm export cannot carry comments.** Keycloak deserializes it strictly
  and rejects any unknown field, so a `"//": "..."` key — the usual trick for
  annotating JSON — fails the whole import with `Unrecognized field "//"` and
  the container never becomes healthy. Explain the realm in the README instead.
- **The issuer URL has to work for clients outside Docker.** Pin `KC_HOSTNAME`
  to `http://localhost:<port>`, because that string ends up in every token's
  `iss` claim and in the metadata document an MCP host reads to find where to
  sign in. A host runs on the developer's machine and cannot resolve
  `keycloak:8080`. Set `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` alongside it so
  containers can still reach the token and key endpoints by service name, and
  give the server `OIDC_JWKS_URL` pointing at that service name — otherwise it
  tries to fetch keys from a `localhost` it cannot resolve.
- **Anonymous Dynamic Client Registration does not work out of the box, and
  should not be made to.** A fresh realm ships a `Trusted Hosts` policy with an
  empty host list, so any DCR attempt gets
  `403 insufficient_scope ... Host not trusted` — which surfaces in Claude Code
  as a failed connection at `claude mcp add` time. Adding trusted hosts still
  leaves the `Full Scope Disabled` policy in place, which turns off
  `fullScopeAllowed` on the registered client, so its tokens carry no realm
  roles and every tool call fails an authorization check that looks like a bug
  in `require_role`. Register the client in the realm export and have the host
  name it with `--client-id`.
- **Only the interactive client issues refresh tokens.** The Client Credentials
  grant deliberately does not, per OAuth 2.1 — a client holding its own secret
  re-mints instead. So a project whose realm has only service accounts has no
  way for a host to stay connected past the access token's lifetime.

## Container and compose details

- **The metadata document is the right healthcheck.** `/.well-known/oauth-protected-resource`
  must answer without a token — it is how a client finds the issuer. Returning
  200 proves the app is serving *and* that the auth layer is configured, which a
  bare TCP connect does not.
- **Retry the issuer discovery.** A local Keycloak is still importing its realm
  when the server container starts. Without a retry the process exits and only
  the restart policy saves it, turning an ordinary race into a crash in the logs.
- **`docker compose run` activates only the target's own profiles, not its
  dependencies'.** A `test-auth` service in profile `auth-test` that depends on a
  `keycloak` in profile `dev` fails with `no such service: keycloak`. List
  Keycloak in both profiles.
- **A profile-gated service is still started by `up`.** Putting a run-and-exit
  test in the same profile as Keycloak means `--profile dev up` runs the test as
  a service. Give it its own profile.
- **Several services sharing one `build:` and one `image:` tag can race** under
  buildkit, failing with `image ... already exists`. Keeping the test services
  out of the profile you `up` avoids building three copies at once.
- **PyJWT arrives today as a transitive dependency of `mcp`**, and `jwt` imports
  without being declared. Pin `PyJWT[crypto]` explicitly anyway; the `crypto`
  extra is what supplies RS256.
