"""In-process check of CountryInfo: tool wiring and the role boundary.

Client talks to the server object in memory — no subprocess, no network to the
server itself — so this is fast and runs with Keycloak stopped and the container
down.

What this checks, and what it cannot:

  * It checks AUTHORIZATION. The auth context is set directly, so one run
    exercises the allow and the deny path for every tool in about a second.
  * It cannot check AUTHENTICATION at all. The in-process client never crosses
    the HTTP layer where tokens are verified, so a completely broken verifier
    still looks fine here. test_auth.py is what covers that. Run both.

The tools also call the REST Countries API, which needs a key, so the data
checks come in groups:

  * Role and bad-argument checks always run. They cover the boundary and every
    argument a tool rejects before making a request.
  * Demo-key checks run when RESTCOUNTRIES_API_KEY is unset. The demo key
    answers every query with the same canned Canada record, so the only correct
    behaviour is to refuse — and that refusal is what gets checked.
  * Live checks run only with a real key and outbound network. They are the only
    group that proves the tools return true data.

Splitting them this way keeps "the environment is not set up" from looking like
"the tools are wrong". Each check is named and the script exits non-zero if any
fails. Run it with:

    docker compose run --rm test
"""

import asyncio
import sys

import httpx
from mcp import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from country_info_server import (
    API_BASE,
    API_KEY,
    ROLE_READ,
    ROLE_SEARCH,
    USING_DEMO_KEY,
    mcp,
)

FAILURES: list[str] = []
SKIPPED: list[str] = []

READ_TOOLS = ("list_countries", "get_country")
SEARCH_TOOLS = ("search_by_currency", "search_by_language")
ALL_TOOLS = READ_TOOLS + SEARCH_TOOLS

# Arguments that would succeed for a caller holding the tool's role. Every tool
# here is read-only, so none of these change anything.
CALLS = {
    "list_countries": {},
    "get_country": {"name_or_code": "FRA"},
    "search_by_currency": {"currency_code": "EUR"},
    "search_by_language": {"language": "spanish"},
}

ROLE_OF = dict.fromkeys(READ_TOOLS, ROLE_READ) | dict.fromkeys(
    SEARCH_TOOLS, ROLE_SEARCH)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAILURES.append(name)


def skip(name: str, why: str) -> None:
    print(f"SKIP  {name} — {why}")
    SKIPPED.append(name)


def error_text(result) -> str:
    """The message a model would read off a failed call."""
    return result.content[0].text if result.content else ""


def payload(result) -> dict:
    """structured_content, or an empty dict when the call failed."""
    return result.structured_content or {}


def results(result) -> list:
    """The list a tool returning list[...] produced, or empty on failure."""
    value = payload(result).get("result")
    return value if isinstance(value, list) else []


def as_identity(subject: str, roles: list[str]) -> None:
    """Make subsequent in-process tool calls run as `subject` holding `roles`.

    This is the same contextvar the server's auth middleware sets from a
    verified token, so require_role() cannot tell the difference. That is the
    point — and also why this belongs only in a test.
    """
    auth_context_var.set(AuthenticatedUser(AccessToken(
        token="in-process-test",
        client_id=subject,
        scopes=roles,
        expires_at=None,
        subject=subject,
    )))


async def check_denied(client, who: str, tool: str, role: str) -> None:
    """Assert a tool refuses the current identity, and says which role it wanted.

    Checking the message and not just is_error matters: if the tool raised
    anything other than ToolError, the text collapses to "Error executing tool
    <tool>" and the caller is told it failed without being told why.
    """
    r = await client.call_tool(tool, CALLS[tool])
    msg = error_text(r)
    check(f"{who} is denied {tool}", r.is_error, msg[:160])
    check(f"the {tool} denial names {role}", role in msg, f"got {msg[:160]!r}")


# ---- The role boundary ----------------------------------------------------

async def role_checks() -> None:
    """A reader, a search-capable caller, and no identity at all."""
    print("\n-- role boundary --")

    # A caller holding only the base role: the two lookup tools work, the two
    # search tools are refused.
    as_identity("test-reader", [ROLE_READ])
    async with Client(mcp) as client:
        for tool in READ_TOOLS:
            r = await client.call_tool(tool, CALLS[tool])
            # The call may still fail on the API key; what matters here is that
            # it was not turned away for the role.
            msg = error_text(r)
            check(f"reader is allowed past the role check on {tool}",
                  ROLE_READ not in msg, msg[:160])
        for tool in SEARCH_TOOLS:
            await check_denied(client, "reader", tool, ROLE_SEARCH)

    # A caller holding both roles: nothing is refused for lack of a role.
    as_identity("test-searcher", [ROLE_READ, ROLE_SEARCH])
    async with Client(mcp) as client:
        for tool in ALL_TOOLS:
            r = await client.call_tool(tool, CALLS[tool])
            msg = error_text(r)
            check(f"searcher is allowed past the role check on {tool}",
                  ROLE_READ not in msg and ROLE_SEARCH not in msg, msg[:160])

    # No identity at all. Over HTTP this is unreachable, because the handshake
    # rejects it first; in process it is what a verified token carrying no roles
    # would look like.
    auth_context_var.set(None)
    async with Client(mcp) as client:
        for tool in ALL_TOOLS:
            r = await client.call_tool(tool, CALLS[tool])
            msg = error_text(r)
            check(f"an unauthenticated caller is refused {tool}", r.is_error,
                  msg[:160])
            check(f"the {tool} refusal says the caller is not authenticated",
                  "not authenticated" in msg, f"got {msg[:160]!r}")


# ---- Everything below runs as a fully privileged caller -------------------

async def listing_checks(client: Client) -> None:
    """Registration, descriptions, and the schemas the model reads."""
    print("\n-- tool listing --")
    listing = await client.list_tools()
    names = [t.name for t in listing.tools]
    print("Tools:", names)
    check("every expected tool is registered", set(ALL_TOOLS) <= set(names),
          f"got {names}")
    check("every tool has a description the model can read",
          all(t.description for t in listing.tools),
          f"missing: {[t.name for t in listing.tools if not t.description]}")
    check("every tool's description names the role it needs",
          all("countries:" in (t.description or "") for t in listing.tools
              if t.name in ALL_TOOLS),
          "a tool description does not mention its role")
    check("the server instructions name both roles",
          ROLE_READ in (mcp.instructions or "")
          and ROLE_SEARCH in (mcp.instructions or ""),
          "instructions do not name both roles")

    schema = next(t.input_schema for t in listing.tools if t.name == "get_country")
    check("get_country requires name_or_code",
          schema.get("required") == ["name_or_code"], repr(schema.get("required")))
    schema = next(
        t.input_schema for t in listing.tools if t.name == "list_countries")
    check("list_countries makes region optional",
          not schema.get("required"), repr(schema.get("required")))


async def bad_argument_checks(client: Client) -> None:
    """Every argument a tool rejects before it makes a request.

    These run as a privileged caller on purpose: require_role() comes first in
    each tool, so an under-privileged caller would get the role error here and
    the argument validation would never be reached.
    """
    print("\n-- bad arguments --")
    r = await client.call_tool("get_country", {"name_or_code": "   "})
    msg = error_text(r)
    check("empty name_or_code is flagged as an error", r.is_error, repr(msg))
    check("the empty-name message reaches the caller intact",
          "must not be empty" in msg,
          f"got {msg!r} — if this is bare 'Error executing tool', the tool "
          f"raised something other than ToolError and its message was dropped")

    r = await client.call_tool("list_countries", {"region": "Atlantis"})
    msg = error_text(r)
    check("an unknown region is flagged as an error", r.is_error, repr(msg))
    check("the unknown-region message lists the valid regions",
          "Africa" in msg and "Oceania" in msg, repr(msg))

    r = await client.call_tool("search_by_currency", {"currency_code": ""})
    check("an empty currency code is rejected with its message intact",
          r.is_error and "must not be empty" in error_text(r),
          repr(error_text(r)))

    r = await client.call_tool("search_by_language", {"language": ""})
    check("an empty language is rejected with its message intact",
          r.is_error and "must not be empty" in error_text(r),
          repr(error_text(r)))


async def demo_key_checks(client: Client) -> None:
    """With no real key, every tool must refuse rather than return fiction."""
    print("\n-- demo key --")
    print("RESTCOUNTRIES_API_KEY is unset, so the demo key is in use. It "
          "returns the same canned Canada record for every query, so the tools "
          "are expected to refuse.")
    for tool in ALL_TOOLS:
        r = await client.call_tool(tool, CALLS[tool])
        msg = error_text(r)
        check(f"{tool} refuses to answer on the demo key", r.is_error, repr(msg))
        check(f"{tool} explains that a key must be configured",
              "RESTCOUNTRIES_API_KEY" in msg, repr(msg))

    check("the server instructions warn that no key is configured",
          "RESTCOUNTRIES_API_KEY" in (mcp.instructions or ""),
          repr((mcp.instructions or "")[-200:]))

    for tool in ALL_TOOLS:
        skip(f"live data checks for {tool}", "no API key configured")


async def live_checks(client: Client) -> None:
    """One call per tool against the real API, plus two not-found cases."""
    print("\n-- live data --")
    r = await client.call_tool("list_countries", {})
    check("list_countries succeeds", not r.is_error, error_text(r))
    entries = results(r)
    check("list_countries pages through the whole dataset", len(entries) > 200,
          f"got {len(entries)} entries")
    check("list_countries pairs each name with its code",
          any(e.startswith("France (FRA)") for e in entries),
          "no 'France (FRA)' entry")

    r = await client.call_tool("list_countries", {"region": "europe"})
    check("a lower-case region still matches", not r.is_error, error_text(r))
    entries = results(r)
    check("the region filter narrows the list", 30 < len(entries) < 100,
          f"got {len(entries)} entries")

    r = await client.call_tool("get_country", {"name_or_code": "FRA"})
    check("get_country resolves a three-letter code", not r.is_error,
          error_text(r))
    got = payload(r)
    check("get_country returns the right country",
          got.get("common_name") == "France", repr(got.get("common_name")))
    check("get_country returns the capital", got.get("capitals") == ["Paris"],
          repr(got.get("capitals")))
    check("get_country returns currencies keyed by code",
          "EUR" in (got.get("currencies") or {}), repr(got.get("currencies")))
    check("get_country returns borders as three-letter codes",
          "ESP" in (got.get("borders") or []), repr(got.get("borders")))
    check("get_country returns the area in square kilometres",
          500_000 < (got.get("area_sq_km") or 0) < 700_000,
          repr(got.get("area_sq_km")))

    r = await client.call_tool("get_country", {"name_or_code": "US"})
    check("get_country resolves a two-letter code",
          not r.is_error and payload(r).get("code_3") == "USA",
          error_text(r) or repr(payload(r).get("code_3")))

    r = await client.call_tool("get_country", {"name_or_code": "Japan"})
    check("get_country resolves a common name", not r.is_error, error_text(r))
    check("the name lookup picks the exact match",
          payload(r).get("code_3") == "JPN", repr(payload(r).get("code_3")))

    r = await client.call_tool("search_by_currency", {"currency_code": "eur"})
    check("search_by_currency succeeds on a lower-case code", not r.is_error,
          error_text(r))
    countries = results(r)
    check("search_by_currency finds the euro countries", len(countries) > 20,
          f"got {len(countries)}")
    check("each currency result carries a code get_country accepts",
          bool(countries) and all(len(c["code"]) == 3 for c in countries),
          repr(countries[:2]))

    r = await client.call_tool("search_by_language", {"language": "spanish"})
    check("search_by_language succeeds", not r.is_error, error_text(r))
    countries = results(r)
    check("search_by_language finds the Spanish-speaking countries",
          len(countries) > 15, f"got {len(countries)}")

    # Not-found cases: these reach the API, match nothing, and must come back as
    # an error the model can act on rather than an empty success.
    r = await client.call_tool("get_country", {"name_or_code": "Wakanda"})
    msg = error_text(r)
    check("an unknown country is flagged as an error", r.is_error, repr(msg))
    check("the unknown-country message says what to do next",
          "list_countries" in msg, repr(msg))

    r = await client.call_tool("search_by_currency", {"currency_code": "ZZZ"})
    msg = error_text(r)
    check("an unknown currency is flagged as an error", r.is_error, repr(msg))
    check("the unknown-currency message names the standard",
          "ISO 4217" in msg, repr(msg))


async def api_reachable() -> bool:
    """One cheap probe, so a missing network shows up once and not per check."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            response = await client.get(
                f"{API_BASE}/codes.alpha_3/CAN",
                headers={"Authorization": f"Bearer {API_KEY}"},
                params={"response_fields": "names.common"},
            )
        return response.status_code < 500
    except httpx.HTTPError:
        return False


async def main() -> None:
    await role_checks()

    # Everything from here runs as a caller holding both roles, so a failure is
    # about the tool rather than the boundary.
    as_identity("test-searcher", [ROLE_READ, ROLE_SEARCH])
    async with Client(mcp) as client:
        await listing_checks(client)
        await bad_argument_checks(client)

        if USING_DEMO_KEY:
            await demo_key_checks(client)
        elif await api_reachable():
            await live_checks(client)
        else:
            print(f"\nCannot reach {API_BASE} — skipping the live checks. This "
                  "is a network problem in this environment, not a tool "
                  "failure.")
            for tool in ALL_TOOLS:
                skip(f"live data checks for {tool}", "API unreachable")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        sys.exit(1)
    if SKIPPED:
        print(f"All checks passed; {len(SKIPPED)} were skipped. Set "
              "RESTCOUNTRIES_API_KEY and rerun to check against real data.")
    else:
        print("All checks passed.")
    print("Authorization is covered here. Authentication is NOT — this test "
          "never crosses the HTTP layer where tokens are verified. Run "
          "`docker compose run --rm test-auth` for that.")


if __name__ == "__main__":
    asyncio.run(main())
