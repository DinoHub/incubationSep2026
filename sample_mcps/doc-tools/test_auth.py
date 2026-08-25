"""Full-stack authentication and authorization check for DocTools.

This runs over real HTTP with real tokens, which is the only way to test
authentication at all: the in-process client in test_server.py never passes
through the HTTP layer where tokens are checked, so it can verify roles but
never the verifier. Run both.

    docker compose --profile dev up -d
    docker compose --profile dev run --rm test-auth

Each check is named and the script exits non-zero if any fails.
"""

import asyncio
import os
import sys

import httpx2

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

TOKEN_URL = os.environ["TOKEN_URL"]
TARGET_URL = os.environ["TARGET_URL"]
ROLE_READ = os.environ.get("ROLE_READ", "documents:read")
ROLE_WRITE = os.environ.get("ROLE_WRITE", "documents:write")

# The interactive client an MCP host signs in through, and a human login to
# sign in as. Used only by the refresh section below.
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "claude-code")
OAUTH_USERNAME = os.environ.get("OAUTH_USERNAME", "dev-writer")
OAUTH_PASSWORD = os.environ.get("OAUTH_PASSWORD", "dev-writer-password")
# The issuer URL this server publishes to clients. It has to be one a host on
# the developer's machine can actually reach.
EXPECTED_ISSUER = os.environ.get("EXPECTED_ISSUER", "")

IDENTITIES = {
    "reader": (os.environ["READER_CLIENT_ID"], os.environ["READER_SECRET"], {ROLE_READ}),
    "writer": (os.environ["WRITER_CLIENT_ID"], os.environ["WRITER_SECRET"], {ROLE_READ, ROLE_WRITE}),
}

# The file the read rows below act on. It is created by setup() before the
# matrix runs, so this test does not depend on seed data or on a previous run
# having left something behind.
PROBE = "auth-probe.txt"

# One row per tool: its name, the role it requires, and arguments that would
# succeed if the caller held that role. The matrix below is derived from this —
# an identity holding the role must succeed, one without it must be refused, and
# the denial must name the role. The write row really runs, so it writes only
# the probe file.
EXPECTATIONS: list[tuple[str, str, dict]] = [
    ("list_files", ROLE_READ, {}),
    ("file_info", ROLE_READ, {"name": PROBE}),
    ("read_file", ROLE_READ, {"name": PROBE, "start_line": 1, "max_lines": 10}),
    ("search_files", ROLE_READ, {"query": "probe"}),
    ("write_file", ROLE_WRITE, {"name": PROBE, "content": "probe written by test_auth\n"}),
]

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAILURES.append(name)


def get_token(client_id: str, secret: str) -> str:
    """Client Credentials grant: the caller authenticates as itself, not as a user."""
    r = httpx2.post(TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": secret,
    }, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def get_token_pair(client_id: str, username: str, password: str) -> dict:
    """Sign in as a person and get an access token *and* a refresh token.

    A real MCP host gets this pair through the authorization-code flow with
    PKCE, which needs a browser. The password grant reaches the same place
    without one, which is the only reason this realm enables it: what matters
    for the test is that the pair comes back and that the refresh half works.
    """
    r = httpx2.post(TOKEN_URL, data={
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
        "scope": "openid",
    }, timeout=15)
    r.raise_for_status()
    return r.json()


def refresh(client_id: str, refresh_token: str) -> dict:
    """Trade a refresh token for a fresh access token.

    This is what keeps a host connected past the access token's lifetime, and
    it is why a short access token costs nothing: the host does this on its own
    when a call comes back 401, with no one pasting anything.
    """
    r = httpx2.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }, timeout=15)
    r.raise_for_status()
    return r.json()


def connect(token: str | None):
    """Open an MCP session, optionally carrying a bearer token.

    The token travels as an ordinary Authorization header. MCP's auth layer
    sits on top of Streamable HTTP; it does not invent its own credential
    transport, which is why a pre-configured HTTP client is all it takes.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    http_client = httpx2.AsyncClient(headers=headers, timeout=20)
    return Client(streamable_http_client(TARGET_URL, http_client=http_client))


def text_of(result) -> str:
    return result.content[0].text if result.content else ""


INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "test-auth", "version": "1"}},
}


def raw_post(token: str | None) -> httpx2.Response:
    """Speak to the endpoint directly, bypassing the MCP client.

    Asserting on the status code is the honest way to test authentication. Going
    through the client instead buries the failure in a nested ExceptionGroup
    whose innermost message is only "Server returned an error response" — no
    status, nothing to distinguish a 401 from a crash.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx2.post(TARGET_URL, json=INITIALIZE, headers=headers, timeout=20)


async def expect_no_session(label: str, token: str | None) -> None:
    """The MCP client should not be able to open a session either.

    Worth checking alongside the raw status code, because it is the failure a
    real caller actually experiences: authentication is enforced during the
    handshake, so the session never opens and no tool is ever reachable. A role
    denial, by contrast, arrives as a normal tool result marked as an error.
    """
    try:
        async with connect(token) as client:
            await client.list_tools()
    except Exception:
        check(f"{label} cannot open an MCP session", True, "")
        return
    check(f"{label} cannot open an MCP session", False, "the handshake succeeded")


async def main() -> None:
    # ---- Authentication: the connection-level boundary -------------------
    r = raw_post(None)
    check("a request with no token is rejected with 401", r.status_code == 401,
          f"got HTTP {r.status_code}")
    # The spec wants the 401 to say where a token can be obtained; without this
    # header a compliant client has no way to start the OAuth flow.
    www = r.headers.get("www-authenticate", "")
    check("the 401 carries a WWW-Authenticate header naming the metadata document",
          "resource_metadata" in www, f"got {www[:160]!r}")

    r = raw_post("not-a-real-jwt")
    check("a request with a forged token is rejected with 401", r.status_code == 401,
          f"got HTTP {r.status_code}")

    # The metadata document is the one endpoint that must answer unauthenticated
    # — it is how a client discovers the issuer in the first place.
    meta_url = TARGET_URL.rsplit("/", 1)[0] + "/.well-known/oauth-protected-resource"
    meta = httpx2.get(meta_url, timeout=20)
    check("the protected-resource metadata document is readable without a token",
          meta.status_code == 200, f"got HTTP {meta.status_code} from {meta_url}")

    await expect_no_session("a caller with no token", None)
    await expect_no_session("a caller with a forged token", "not-a-real-jwt")

    # The metadata document is also what tells a host where to sign in, so its
    # authorization_servers entry has to be a URL the host can reach. A Docker
    # service name passes every other check in this file and still leaves an
    # MCP host unable to authenticate, because it runs outside the network.
    if EXPECTED_ISSUER:
        advertised = meta.json().get("authorization_servers", []) if meta.status_code == 200 else []
        check("the metadata document names an issuer a host outside Docker can reach",
              EXPECTED_ISSUER in advertised,
              f"advertises {advertised}, expected {EXPECTED_ISSUER!r}")

    # ---- Refresh: staying connected past the access token's lifetime -----
    # Without this, a host holding a five-minute access token simply stops
    # working after five minutes, and someone has to paste in a new one. The
    # refresh token is what removes the person from that loop.
    pair = get_token_pair(OAUTH_CLIENT_ID, OAUTH_USERNAME, OAUTH_PASSWORD)
    check("signing in returns an access token", bool(pair.get("access_token")), str(pair)[:160])
    check("signing in also returns a refresh token", bool(pair.get("refresh_token")),
          "no refresh_token in the response — a host would have nothing to renew with")
    check("the refresh token outlives the access token",
          pair.get("refresh_expires_in", 0) > pair.get("expires_in", 0),
          f"access {pair.get('expires_in')}s, refresh {pair.get('refresh_expires_in')}s")

    async with connect(pair["access_token"]) as client:
        listing = await client.list_tools()
        check("a signed-in user can open a session", bool(listing.tools),
              f"got {len(listing.tools)} tools")

    renewed = refresh(OAUTH_CLIENT_ID, pair["refresh_token"])
    check("the refresh token buys a new access token", bool(renewed.get("access_token")),
          str(renewed)[:160])
    check("the new access token is genuinely new",
          renewed.get("access_token") != pair.get("access_token"),
          "the same token came back, so nothing was actually renewed")

    async with connect(renewed["access_token"]) as client:
        listing = await client.list_tools()
        check("the renewed token is accepted by the server", bool(listing.tools),
              f"got {len(listing.tools)} tools")
        # Roles survive the renewal. A refreshed token that lost them would
        # authenticate fine and then fail every tool call, which is a confusing
        # way to discover the scope was dropped.
        r2 = await client.call_tool("write_file", {"name": PROBE, "content": "renewed\n"})
        check("the renewed token still carries the caller's roles",
              not r2.is_error, text_of(r2)[:160])

    # ---- Authorization: the per-tool boundary ---------------------------
    # The read rows need a file to read. Create it as the writer first, so the
    # matrix does not depend on seed data or on what a previous run left behind.
    writer_id, writer_secret, _ = IDENTITIES["writer"]
    async with connect(get_token(writer_id, writer_secret)) as client:
        r = await client.call_tool("write_file", {"name": PROBE, "content": "probe written by test_auth\n"})
        check("setup: the writer can create the probe file", not r.is_error, text_of(r)[:160])

    if not EXPECTATIONS:
        check("EXPECTATIONS is filled in", False,
              "no tools listed — the role boundary was not tested at all")

    for who, (client_id, secret, held) in IDENTITIES.items():
        token = get_token(client_id, secret)
        async with connect(token) as client:
            listing = await client.list_tools()
            check(f"{who} can open a session and list tools",
                  bool(listing.tools), f"got {len(listing.tools)} tools")

            for tool, role, args in EXPECTATIONS:
                r = await client.call_tool(tool, args)
                msg = text_of(r)
                if role in held:
                    check(f"{who} may call {tool} (holds {role})",
                          not r.is_error, msg[:160])
                else:
                    check(f"{who} is denied {tool} (lacks {role})", r.is_error, msg[:160])
                    # A denial the caller cannot act on is nearly useless. If
                    # this fails while the one above passes, the tool raised
                    # something other than ToolError and its message was
                    # replaced with a bare "Error executing tool <name>".
                    check(f"the {tool} denial names the missing role",
                          role in msg, f"got {msg[:160]!r}")

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
