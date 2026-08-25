"""Authentication and authorization for DocTools.

Two separate jobs live here, and the MCP server checks them at different moments:

- **Authentication** — is this a real, unexpired token signed by our issuer?
  MCPServer runs this during the connection handshake, before any tool is
  reachable. A missing or bad token gets a real HTTP 401 and the connection is
  refused, so no tool code runs at all.
- **Authorization** — is this caller allowed to run *this* tool? That question
  only makes sense once a specific tool is being called inside an
  already-authenticated session, so it happens per call via require_role().
  There is no per-tool HTTP status in MCP; a denial comes back as a tool result
  marked as an error.

The server never sees a client secret. It only ever sees a bearer token, and it
verifies that token against the issuer's published signing keys — the trust
model of checking a signature, not of checking a password.

Nothing here reads the environment or touches the network at import time. That
matters: the in-process test imports the server module, and therefore this
module, without any OIDC configuration at all. Configuration is read the first
time it is actually needed, which is when a token arrives.
"""

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from pydantic import AnyHttpUrl

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError

DEFAULT_PORT = "8000"


# ---- Configuration ------------------------------------------------------
# Everything that differs between a local Keycloak and a real provider is an
# environment variable, so the same image runs in both places.

@dataclass(frozen=True)
class Config:
    issuer: str
    audience: str | None
    server_url: str
    roles_claim: str
    algorithms: tuple[str, ...]
    jwks_url_override: str | None


@lru_cache(maxsize=1)
def config() -> Config:
    issuer = os.environ.get("OIDC_ISSUER")
    if not issuer:
        raise RuntimeError(
            "OIDC_ISSUER is not set, so tokens cannot be verified. Set it to your "
            "provider's issuer URL, or start the bundled Keycloak with: "
            "docker compose --profile dev up -d"
        )
    return Config(
        issuer=issuer.rstrip("/"),
        # Optional but strongly recommended in production: the identifier this
        # server is registered under with the issuer. Left unset, any token the
        # issuer signed is accepted, including one minted for a different
        # service. See references/oidc-providers.md for why that matters.
        audience=os.environ.get("OIDC_AUDIENCE") or None,
        # Where this server is reachable. Only used to fill in the Protected
        # Resource Metadata document, not to restrict which hostname callers
        # connect through.
        server_url=os.environ.get("SERVER_URL", f"http://localhost:{DEFAULT_PORT}"),
        # Dotted path to the claim holding the caller's roles. Providers
        # disagree: Keycloak uses realm_access.roles, Auth0 permissions, Okta
        # scp, Entra roles.
        roles_claim=os.environ.get("OIDC_ROLES_CLAIM", "realm_access.roles"),
        algorithms=tuple(a.strip() for a in os.environ.get("OIDC_ALGORITHMS", "RS256").split(",") if a.strip()),
        jwks_url_override=os.environ.get("OIDC_JWKS_URL") or None,
    )


def _discover_jwks_url(cfg: Config) -> str:
    """Find the signing-key endpoint from the issuer's discovery document.

    Reading jwks_uri out of /.well-known/openid-configuration is what makes this
    work against any compliant provider instead of only Keycloak, whose JWKS
    path is not the same as Auth0's or Okta's.
    """
    if cfg.jwks_url_override:
        return cfg.jwks_url_override
    discovery = f"{cfg.issuer}/.well-known/openid-configuration"

    # Retry before giving up. An issuer is routinely not ready at the moment
    # this container starts — a local Keycloak is still importing its realm, or
    # a hosted provider drops one request. Without this, an ordinary startup
    # race becomes a crash in the logs.
    last: Exception | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(discovery, timeout=10) as r:
                return json.load(r)["jwks_uri"]
        except (OSError, KeyError, ValueError) as exc:
            last = exc
            if attempt < 5:
                time.sleep(2 * (attempt + 1))  # 2s, 4s, 6s, 8s, 10s
    # Still failing after ~30s: this is configuration, not a race. Name both
    # likely causes, because an unreachable issuer and a misconfigured one look
    # identical from here.
    raise RuntimeError(
        f"Could not fetch OIDC discovery from {discovery!r} after 6 attempts: {last}. "
        f"Either OIDC_ISSUER points somewhere wrong, or the issuer is not running — "
        f"for the bundled Keycloak, start it with: docker compose --profile dev up -d"
    ) from last


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    """PyJWKClient caches the fetched keys, so verification costs one network
    call for the lifetime of the process rather than one per request. Verifying
    a self-contained signed JWT locally is why this server never has to call the
    issuer's introspection endpoint."""
    return PyJWKClient(_discover_jwks_url(config()))


def _extract_roles(claims: dict, roles_claim: str) -> list[str]:
    """Pull the role list out of whichever claim this provider uses.

    Handles both shapes providers use: a JSON array, and the space-delimited
    string that the standard `scope` claim carries.
    """
    node: object = claims
    for part in roles_claim.split("."):
        if not isinstance(node, dict):
            node = None
            break
        node = node.get(part)
    if node is None:
        # Fall back to the standard claims before giving up, so a provider using
        # plain `scope` works with no configuration.
        node = claims.get("scope") or claims.get("scp") or []
    if isinstance(node, str):
        return node.split()
    return list(node) if isinstance(node, (list, tuple)) else []


# ---- Authentication -----------------------------------------------------

class JWKSTokenVerifier(TokenVerifier):
    """Verifies a JWT locally against the issuer's published signing key.

    The MCP spec's own tutorial verifies tokens through the issuer's
    introspection endpoint instead. That is also valid, but it requires
    registering this server as its own confidential client and costs a network
    round trip per call. A self-contained signed JWT needs neither.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        cfg = config()
        try:
            signing_key = _jwk_client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(cfg.algorithms),
                issuer=cfg.issuer,
                audience=cfg.audience,
                # Skip the audience check only when no audience is configured.
                # Returning None rather than raising is deliberate: the SDK turns
                # None into a 401, and the caller learns nothing about *why* the
                # token was rejected, which is what you want at this edge.
                options={"verify_aud": cfg.audience is not None},
            )
        except jwt.PyJWTError:
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("azp") or claims.get("client_id") or "unknown",
            scopes=_extract_roles(claims, cfg.roles_claim),
            expires_at=claims.get("exp"),
            subject=claims.get("preferred_username") or claims.get("sub"),
            claims=claims,
        )


def auth_settings() -> AuthSettings:
    """Server-level auth configuration.

    required_scopes is deliberately empty: any authenticated caller may open a
    connection, and which *tools* it can run is checked per call by
    require_role() below. The MCP spec's "Common Pitfalls" guidance says exactly
    this — verify required scopes per tool on the resource server, rather than
    gating everything behind one catch-all scope.
    """
    cfg = config()
    return AuthSettings(
        issuer_url=AnyHttpUrl(cfg.issuer),
        resource_server_url=AnyHttpUrl(cfg.server_url),
        required_scopes=[],
    )


# ---- Authorization ------------------------------------------------------

def require_role(role: str) -> AccessToken:
    """Assert the current caller holds `role`, or refuse the call.

    Call this as the first line of any tool that needs a privilege. By the time
    a tool runs, authentication has already happened — an unauthenticated
    request never got this far. This is the other case: a real, verified
    identity that simply does not hold the role this tool requires.

    Needs no configuration, which is what lets the in-process test exercise the
    whole role boundary without an issuer.

    ToolError is what makes the denial useful. Any other exception type has its
    message replaced by a bare "Error executing tool <name>", so the caller
    would be told it failed and never told which role it was missing.
    """
    token = get_access_token()
    if token is None:
        # No auth context at all. Over HTTP this is unreachable, because the
        # handshake already rejected the request. In an in-process test it means
        # the test did not set an identity — see the note in test_server.py.
        raise ToolError(
            f"This tool requires the {role!r} role, but the caller is not "
            f"authenticated. Connect with a bearer token."
        )
    if role not in token.scopes:
        raise ToolError(
            f"{token.subject!r} has roles {sorted(token.scopes)}, but this "
            f"action needs {role!r}."
        )
    return token
