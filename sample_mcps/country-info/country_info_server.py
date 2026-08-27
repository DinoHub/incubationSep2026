"""CountryInfo — an MCP server wrapping the REST Countries API (v5).

Run over stdio:            python country_info_server.py
Run over Streamable HTTP:  python http_server.py

The API needs a key. Set RESTCOUNTRIES_API_KEY in the environment; a free key
comes from https://restcountries.com/sign-up. With no key set, the server falls
back to the published demo key, which returns the same canned Canada record for
every query — so the tools refuse to answer rather than hand a model fake data.

Field paths follow v5 (names.common, codes.alpha_3, area.kilometers, ...). The
older v3.1 API this kind of wrapper used to target was retired and now serves
only a deprecation notice, so v3.1 field names will not work here.
"""

import os
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from auth import JWKSTokenVerifier, auth_settings, require_role
from mcp.server import MCPServer

# ToolError is the one exception whose message reaches the model. Anything else
# is wrapped as "Error executing tool <name>" with your text withheld, so use
# this for every failure the model is meant to read and recover from. It lives
# only on this path — it is not re-exported from mcp or mcp.server.
from mcp.server.mcpserver.exceptions import ToolError

# Roles. Looking a country up is the ordinary case and needs only the base
# role; the two search tools sweep the whole dataset and each cost several
# upstream requests against a rate-limited, metered key, so they are held back
# behind the second role.
ROLE_READ = "countries:read"
ROLE_SEARCH = "countries:search"

API_BASE = "https://api.restcountries.com/countries/v5"
SIGNUP_URL = "https://restcountries.com/sign-up"

# The key the docs publish for trying the API out. It answers every request with
# one fixed Canada record plus a data._demo notice, so it proves the transport
# works and nothing else.
DEMO_KEY = "rc_live_demo"
API_KEY = os.environ.get("RESTCOUNTRIES_API_KEY", "").strip() or DEMO_KEY
USING_DEMO_KEY = API_KEY == DEMO_KEY

TIMEOUT = httpx.Timeout(20.0)

# Free-plan page ceiling. The full country list is ~250 records, so listing
# everything costs three requests.
MAX_PAGE = 100
# Backstop against an upstream that never reports the end of a result set.
MAX_PAGES = 20

# The regions v5 uses. Kept here so a bad region is rejected with the valid list
# rather than an empty result the model cannot interpret.
REGIONS = ("Africa", "Americas", "Asia", "Europe", "Oceania", "Antarctic")

# Trimmed projection for list and search results — full records carry name
# translations in dozens of languages and a flag colour palette, none of which
# a summary needs.
SUMMARY_FIELDS = "names.common,codes.alpha_3,capitals,region,population"
# Full detail minus the two heaviest branches.
DETAIL_OMIT = "names.translations,flag.colors"

_DEMO_MESSAGE = (
    "This server is using the REST Countries demo key, which answers every "
    "query with the same canned Canada record. The result would be fiction, so "
    "it is being withheld. Ask the operator to get a free key at "
    f"{SIGNUP_URL} and set RESTCOUNTRIES_API_KEY on the server. Retrying will "
    "not help."
)

mcp = MCPServer(
    "CountryInfo",
    instructions=(
        "CountryInfo answers factual questions about countries — capital, "
        "population, area, region, currencies, languages, land borders, and "
        "timezones — from the REST Countries API. It is read-only: nothing "
        "here changes any data.\n\n"
        "Start with list_countries when you do not already know the exact name "
        "or code of the country you want; it takes an optional region filter "
        "and returns every name paired with its three-letter code. Feed either "
        "the name or that code into get_country, which is the only tool that "
        "returns full detail for one country.\n\n"
        "search_by_currency and search_by_language go the other way: they take "
        "a currency code or a language and return the countries that use it, "
        "in summary form. Follow up with get_country when you need more than "
        "name, capital, region, and population.\n\n"
        "Country codes throughout are ISO 3166-1: two letters (US, FR) or "
        "three (USA, FRA). The borders field of get_country holds three-letter "
        "codes, so it can be fed straight back into get_country.\n\n"
        "Every tool requires a role, carried by your bearer token. "
        f"list_countries and get_country each need {ROLE_READ}. "
        f"search_by_currency and search_by_language each need {ROLE_SEARCH}, "
        "which not every caller holds. A call made without the role it needs "
        "comes back as an error naming the missing role; retrying it will not "
        f"help, so report it instead. Without {ROLE_SEARCH} you can still "
        "answer a currency or language question by calling get_country on "
        "specific countries and reading their currencies and languages "
        "fields — it costs more calls, but it works."
        + (
            "\n\nIMPORTANT: this server has no REST Countries API key "
            "configured, so every tool will fail with an explanation instead "
            "of returning data. Tell the user the server operator needs to set "
            f"RESTCOUNTRIES_API_KEY (a free key comes from {SIGNUP_URL}), and "
            "do not try to answer country questions from these tools until "
            "that is done."
            if USING_DEMO_KEY
            else ""
        )
    ),
    # Authentication: verified during the connection handshake, before any tool
    # is reachable. A missing or invalid token is refused with an HTTP 401 and
    # no tool code runs. Authorization is separate — see require_role() at the
    # top of each tool below.
    token_verifier=JWKSTokenVerifier(),
    auth=auth_settings(),
)


class _NotFound(Exception):
    """Upstream returned 404. Callers turn this into a tool-specific message."""


def _errors_text(body: object) -> str:
    """Join the messages out of a v5 error body, which shape they all share."""
    if isinstance(body, dict) and isinstance(body.get("errors"), list):
        messages = [
            str(e.get("message"))
            for e in body["errors"]
            if isinstance(e, dict) and e.get("message")
        ]
        if messages:
            return " ".join(messages)
    return ""


async def _api_get(path: str, params: dict[str, str] | None = None) -> dict:
    """GET one v5 endpoint and return its `data` block.

    Raises _NotFound on 404 so each tool can say what was not found, and
    ToolError for everything else the model can act on: a rejected key, a
    frozen account, a rate limit, an unreachable host, or a demo-key response
    that would be fiction.
    """
    url = f"{API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
    except httpx.HTTPError as exc:
        raise ToolError(
            f"Could not reach the REST Countries API at {url}: {exc}. The "
            "server needs outbound network access; retrying may help if this "
            "was a timeout."
        ) from exc

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code == 404:
        raise _NotFound(url)

    if response.status_code == 401:
        raise ToolError(
            "The REST Countries API rejected this server's key. The operator "
            "needs to set a valid RESTCOUNTRIES_API_KEY; a free key comes from "
            f"{SIGNUP_URL}. Retrying will not help."
        )
    if response.status_code == 403:
        raise ToolError(
            "The REST Countries API refused the request: "
            + (_errors_text(body) or "the account is frozen or the request "
               "needs a paid plan.")
            + " Retrying will not help until the account changes."
        )
    if response.status_code == 429:
        raise ToolError(
            "The REST Countries API rate limit was hit (20 requests per 10 "
            "seconds). Wait a few seconds and retry."
        )
    if response.status_code >= 400:
        detail = _errors_text(body)
        raise ToolError(
            f"The REST Countries API returned HTTP {response.status_code} for "
            f"{url}" + (f": {detail}" if detail else ".")
        )

    if not isinstance(body, dict):
        raise ToolError(
            f"The REST Countries API returned a body that is not a JSON object "
            f"for {url}. This is an upstream failure; retry later."
        )
    detail = _errors_text(body)
    if detail:
        raise ToolError(f"The REST Countries API reported: {detail}")

    data = body.get("data")
    if not isinstance(data, dict):
        raise ToolError(
            f"The REST Countries API response for {url} has no data object. "
            "This is an upstream failure; retry later."
        )
    if "_demo" in data:
        raise ToolError(_DEMO_MESSAGE)
    return data


def _objects(data: dict) -> list[dict]:
    """The country records out of one `data` block."""
    objects = data.get("objects")
    if not isinstance(objects, list):
        raise ToolError(
            "The REST Countries API returned a response with no objects list. "
            "This is an upstream failure; retry later."
        )
    return [o for o in objects if isinstance(o, dict)]


async def _api_get_all(path: str, params: dict[str, str]) -> list[dict]:
    """Page through one endpoint and return every matched record.

    v5 caps a page at 100 records on the free plan and reports `more` in
    data.meta, so anything that can match the whole dataset has to page.
    """
    collected: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        page_params = dict(params, limit=str(MAX_PAGE), offset=str(offset))
        data = await _api_get(path, page_params)
        batch = _objects(data)
        collected.extend(batch)
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        # `more` is authoritative when present; a short page ends the walk
        # otherwise.
        if meta.get("more") is not True or not batch:
            break
        offset += len(batch)
    return collected


# ---- Structured return types ---------------------------------------------
# Returning a BaseModel hands the host a schema and parseable structured
# content instead of a wall of text.

class CountrySummary(BaseModel):
    """One country, enough to tell it apart and decide whether to fetch more."""

    common_name: str
    code: str            # ISO 3166-1 alpha-3, accepted by get_country
    capital: str | None  # None for the few countries with no capital
    region: str
    population: int


class Country(BaseModel):
    """Full detail for one country."""

    common_name: str
    official_name: str
    code_2: str                    # ISO 3166-1 alpha-2, e.g. "FR"
    code_3: str                    # ISO 3166-1 alpha-3, e.g. "FRA"
    capitals: list[str]            # empty for countries with no capital
    region: str
    subregion: str | None
    population: int
    area_sq_km: float
    currencies: dict[str, str]     # code -> name, e.g. {"EUR": "Euro"}
    languages: list[str]           # English names, e.g. ["French"]
    borders: list[str]             # alpha-3 codes; empty for islands
    landlocked: bool
    timezones: list[str]
    flag_emoji: str | None
    un_member: bool
    google_maps_url: str | None


def _first_capital(raw: dict) -> str | None:
    for capital in raw.get("capitals") or []:
        if isinstance(capital, dict) and capital.get("name"):
            return str(capital["name"])
    return None


def _summary(raw: dict) -> CountrySummary:
    """Build a CountrySummary from one v5 country record."""
    names = raw.get("names") or {}
    codes = raw.get("codes") or {}
    return CountrySummary(
        common_name=str(names.get("common") or "unknown"),
        code=str(codes.get("alpha_3") or ""),
        capital=_first_capital(raw),
        region=str(raw.get("region") or "unknown"),
        population=int(raw.get("population") or 0),
    )


def _country(raw: dict) -> Country:
    """Build a Country from one v5 country record."""
    names = raw.get("names") or {}
    codes = raw.get("codes") or {}
    area = raw.get("area") or {}
    flag = raw.get("flag") or {}
    links = raw.get("links") or {}
    classification = raw.get("classification") or {}

    # v5 returns currencies as a list of {code, name, symbol}; flatten to
    # code -> name so a caller can look one up without scanning.
    currencies: dict[str, str] = {}
    for entry in raw.get("currencies") or []:
        if isinstance(entry, dict) and entry.get("code"):
            currencies[str(entry["code"])] = str(entry.get("name") or entry["code"])

    languages = [
        str(entry["name"])
        for entry in raw.get("languages") or []
        if isinstance(entry, dict) and entry.get("name")
    ]

    common = str(names.get("common") or "unknown")
    return Country(
        common_name=common,
        official_name=str(names.get("official") or common),
        code_2=str(codes.get("alpha_2") or ""),
        code_3=str(codes.get("alpha_3") or ""),
        capitals=[
            str(c["name"])
            for c in raw.get("capitals") or []
            if isinstance(c, dict) and c.get("name")
        ],
        region=str(raw.get("region") or "unknown"),
        subregion=str(raw.get("subregion")) if raw.get("subregion") else None,
        population=int(raw.get("population") or 0),
        area_sq_km=float(area.get("kilometers") or 0.0),
        currencies=currencies,
        languages=languages,
        borders=[str(b) for b in raw.get("borders") or []],
        landlocked=bool(raw.get("landlocked")),
        timezones=[str(t) for t in raw.get("timezones") or []],
        flag_emoji=str(flag.get("emoji")) if flag.get("emoji") else None,
        un_member=bool(classification.get("un_member")),
        google_maps_url=(
            str(links.get("google_maps")) if links.get("google_maps") else None
        ),
    )


# ---- Tools ----------------------------------------------------------------
# The type hints ARE the input schema — the SDK generates it, so you never
# hand-write JSON Schema. The docstring is what the model reads to decide
# whether to call a tool, so say what it does and how each parameter behaves.

@mcp.tool()
async def list_countries(region: str | None = None) -> list[str]:
    """List every country as "Common Name (CODE)", sorted by name.

    CODE is the ISO 3166-1 three-letter code, which get_country accepts. Use
    this first whenever you are unsure of a country's exact name or code —
    guessing a name costs a failed call.

    Pass region to narrow the list to one continent-level region. Valid values
    are Africa, Americas, Asia, Europe, Oceania, and Antarctic; the match is
    case-insensitive. Leave it out to get all roughly 250 entries.

    Requires the countries:read role.
    """
    require_role(ROLE_READ)
    if region is None:
        records = await _api_get_all("", {"response_fields": SUMMARY_FIELDS})
    else:
        wanted = region.strip()
        matched = [r for r in REGIONS if r.lower() == wanted.lower()]
        if not matched:
            raise ToolError(
                f"{region!r} is not a region this API knows. Valid regions are: "
                f"{', '.join(REGIONS)}. Omit the region argument to list every "
                "country."
            )
        try:
            records = await _api_get_all(
                f"/region/{quote(matched[0])}",
                {"response_fields": SUMMARY_FIELDS},
            )
        except _NotFound:
            raise ToolError(
                f"The API has no countries for region {matched[0]!r}. Omit the "
                "region argument to list every country."
            ) from None

    return sorted(
        f"{s.common_name} ({s.code})" for s in (_summary(raw) for raw in records)
    )


@mcp.tool()
async def get_country(name_or_code: str) -> Country:
    """Get full detail for one country: capital, region, population, area,
    currencies, languages, land borders, timezones, and flag.

    name_or_code takes either a country name or an ISO 3166-1 code. A code is
    two letters ("FR") or three ("FRA"), matched exactly, and is the reliable
    choice. A name can be common ("France") or official ("French Republic");
    an exact name is tried first, then a partial match, so a fragment resolves
    to the closest single country. Call list_countries if you know neither.

    The returned borders field holds three-letter codes, so each one can be
    passed straight back into this tool to walk a country's neighbours.

    Requires the countries:read role.
    """
    require_role(ROLE_READ)
    query = name_or_code.strip()
    if not query:
        raise ToolError(
            "name_or_code must not be empty. Pass a country name such as "
            "'France' or a code such as 'FRA'. Call list_countries to see "
            "what is available."
        )

    detail = {"response_fields_omit": DETAIL_OMIT}
    records: list[dict] = []

    # A two- or three-letter input is a code, and the code endpoints are exact,
    # so try those first and fall through to a name lookup if they miss.
    if query.isalpha() and len(query) in (2, 3):
        field = "codes.alpha_2" if len(query) == 2 else "codes.alpha_3"
        try:
            records = _objects(await _api_get(f"/{field}/{quote(query)}", detail))
        except _NotFound:
            records = []

    if not records:
        try:
            records = _objects(
                await _api_get(f"/names.common/{quote(query)}", detail)
            )
        except _NotFound:
            records = []

    if not records:
        # Aggregate search over every name field, which is what makes a partial
        # name resolve.
        try:
            records = _objects(await _api_get("/name", dict(detail, q=query)))
        except _NotFound:
            records = []

    if not records:
        raise ToolError(
            f"No country matches {name_or_code!r}. Try the ISO code instead, "
            "or call list_countries to see the exact names and codes available."
        )

    # A partial name can match several countries. Prefer an exact name hit
    # before falling back to the first result, which is alphabetically first.
    def exact(raw: dict) -> bool:
        names = raw.get("names") or {}
        return query.lower() in (
            str(names.get("common", "")).lower(),
            str(names.get("official", "")).lower(),
        )

    return _country(next((raw for raw in records if exact(raw)), records[0]))


@mcp.tool()
async def search_by_currency(currency_code: str) -> list[CountrySummary]:
    """List the countries that use one currency, sorted by name.

    currency_code is an ISO 4217 code such as USD, EUR, or JPY, matched exactly
    and case-insensitively. Currency names are not accepted — pass "EUR", not
    "Euro". Each result carries the country's three-letter code, which
    get_country accepts for full detail.

    Requires the countries:search role, which not every caller holds.
    """
    require_role(ROLE_SEARCH)
    code = currency_code.strip()
    if not code:
        raise ToolError(
            "currency_code must not be empty. Pass an ISO 4217 code such as "
            "'EUR' or 'JPY'."
        )
    try:
        records = await _api_get_all(
            f"/currencies/{quote(code)}", {"response_fields": SUMMARY_FIELDS}
        )
    except _NotFound:
        records = []

    if not records:
        raise ToolError(
            f"No country uses a currency with code {currency_code!r}. Check the "
            "ISO 4217 code — it is three letters, such as 'EUR' for the euro. "
            "Call get_country on a country you know to see its currencies."
        )
    return sorted((_summary(raw) for raw in records), key=lambda s: s.common_name)


@mcp.tool()
async def search_by_language(language: str) -> list[CountrySummary]:
    """List the countries where one language is spoken, sorted by name.

    language is an English language name such as "spanish" or "arabic", or a
    language code such as "es" or "spa". Matching is a case-insensitive
    substring over each country's language entries, so a short fragment can
    pull in more countries than you meant — prefer the full English name. Each
    result carries the country's three-letter code, which get_country accepts
    for full detail.

    Requires the countries:search role, which not every caller holds.
    """
    require_role(ROLE_SEARCH)
    lang = language.strip()
    if not lang:
        raise ToolError(
            "language must not be empty. Pass a language name such as "
            "'spanish' or a code such as 'spa'."
        )
    try:
        records = await _api_get_all(
            "", {"languages": lang, "response_fields": SUMMARY_FIELDS}
        )
    except _NotFound:
        records = []

    if not records:
        raise ToolError(
            f"No country lists {language!r} among its languages. Check the "
            "spelling, try the English name of the language, or try its "
            "language code. Call get_country on a country you know to see its "
            "languages."
        )
    return sorted((_summary(raw) for raw in records), key=lambda s: s.common_name)


# ---- Resources ------------------------------------------------------------
# Read-only context the host can fetch at a URI without spending a model turn.

@mcp.resource("country-info://regions")
def regions() -> str:
    """The region names list_countries accepts, one per line."""
    return "\n".join(REGIONS)


# ---- Prompts --------------------------------------------------------------
# Reusable, parameterized message templates the host can offer the user, often
# as a slash command. Uncomment and adapt if you need it.

# @mcp.prompt()
# def example_prompt(topic: str) -> str:
#     """TODO: describe when a user would reach for this prompt."""
#     return f"TODO: prompt text about {topic}"


if __name__ == "__main__":
    mcp.run()  # stdio by default
