"""In-process check of DocTools: what each tool does, and who may call it.

Client talks to the server object in memory — no subprocess, no network — so
this is fast and runs with the container stopped. Because the auth context is a
plain contextvar, this test can impersonate a reader and a writer, and so cover
the allow and the deny path for every tool in about a second, with no Keycloak.

What this canNOT check is authentication. The in-process client never passes
through the HTTP layer where tokens are verified, so a completely broken
verifier still looks fine here. test_auth.py is what covers that. Run both:

    docker compose run --rm test        # this file
    docker compose run --rm test-auth   # tokens over HTTP, real Keycloak
"""

import asyncio
import sys

from mcp import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from doc_tools_server import WORK_DIR, mcp

ROLE_READ = "documents:read"
ROLE_WRITE = "documents:write"

FAILURES: list[str] = []

# The working directory is a host bind mount, so files survive between runs.
# Clear this run's artifacts up front, or the "creates it" checks would only
# pass the first time.
ARTIFACTS = ["check-notes.txt", "check-other.txt", "check-new.txt", "check-reader.txt"]

BODY = "alpha line one\nBETA line two\nbeta line three\ngamma line four\ndelta line five"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAILURES.append(name)


def as_identity(subject: str, roles: list[str]) -> None:
    """Make subsequent in-process tool calls run as `subject` holding `roles`.

    This is the same contextvar the server's auth middleware sets from a
    verified token, so require_role() cannot tell the difference. That is the
    point — and also why this belongs only in a test. Set it before opening the
    Client, so the tasks the session spawns inherit it.
    """
    auth_context_var.set(AuthenticatedUser(AccessToken(
        token="in-process-test",
        client_id=subject,
        scopes=roles,
        expires_at=None,
        subject=subject,
    )))


async def check_denied(client, who: str, tool: str, args: dict, role: str) -> None:
    """Assert a tool refuses the current identity, and says which role it wanted.

    Checking the message and not just is_error matters: if the tool raised
    anything other than ToolError, the text collapses to "Error executing tool
    <tool>" and the caller is told it failed without being told why.
    """
    r = await client.call_tool(tool, args)
    msg = r.content[0].text if r.content else ""
    check(f"{who} is denied {tool}", r.is_error, msg[:120])
    check(f"the {tool} denial names {role}", role in msg, f"got {msg[:120]!r}")


async def check_tool_behaviour(client) -> None:
    """Every tool's own behaviour, run as an identity holding both roles."""
    # ---- write_file ---------------------------------------------------
    r = await client.call_tool("write_file", {"name": "check-notes.txt", "content": BODY})
    check("write_file creates a file", not r.is_error, str(r.content))
    check("write_file reports the line count",
          (r.structured_content or {}).get("line_count") == 5, repr(r.structured_content))

    r = await client.call_tool("write_file", {"name": "check-other.txt", "content": "beta appears here too\n"})
    check("write_file creates a second file", not r.is_error, str(r.content))

    # ---- list_files ---------------------------------------------------
    r = await client.call_tool("list_files", {})
    files = (r.structured_content or {}).get("result", [])
    check("list_files sees the written files",
          {"check-notes.txt", "check-other.txt"} <= set(files), repr(files))

    # ---- file_info ----------------------------------------------------
    r = await client.call_tool("file_info", {"name": "check-notes.txt"})
    info = r.structured_content or {}
    check("file_info returns size, lines, and modified time",
          info.get("line_count") == 5 and info.get("size_bytes") == len(BODY) and info.get("modified"),
          repr(info))

    # ---- read_file ----------------------------------------------------
    r = await client.call_tool("read_file", {"name": "check-notes.txt"})
    body = r.structured_content or {}
    check("read_file round-trips the whole file by default",
          body.get("text") == BODY and body.get("truncated") is False, repr(body))

    r = await client.call_tool("read_file", {"name": "check-notes.txt", "start_line": 2, "max_lines": 2})
    window = r.structured_content or {}
    check("read_file returns the requested window",
          window.get("text") == "BETA line two\nbeta line three"
          and window.get("start_line") == 2 and window.get("end_line") == 3,
          repr(window))
    check("read_file flags that more lines follow",
          window.get("truncated") is True and window.get("total_lines") == 5, repr(window))

    # ---- search_files -------------------------------------------------
    r = await client.call_tool("search_files", {"query": "beta"})
    hits = (r.structured_content or {}).get("result", [])
    found = {(h["name"], h["line_number"]) for h in hits}
    check("search_files matches case-insensitively across files",
          {("check-notes.txt", 2), ("check-notes.txt", 3), ("check-other.txt", 1)} <= found,
          repr(hits))

    r = await client.call_tool("search_files", {"query": "BETA", "case_sensitive": True})
    hits = (r.structured_content or {}).get("result", [])
    check("search_files honours case_sensitive",
          [(h["name"], h["line_number"]) for h in hits] == [("check-notes.txt", 2)], repr(hits))

    # ---- append -------------------------------------------------------
    r = await client.call_tool("write_file",
                               {"name": "check-notes.txt", "content": "epsilon line six", "mode": "append"})
    check("append adds a line rather than replacing the file",
          (r.structured_content or {}).get("line_count") == 6, repr(r.structured_content))
    r = await client.call_tool("read_file", {"name": "check-notes.txt"})
    text = (r.structured_content or {}).get("text", "")
    check("appended text keeps what was already there",
          text.startswith("alpha line one") and text.endswith("epsilon line six"), repr(text))

    # ---- Error paths --------------------------------------------------
    # These matter as much as the happy path: this is what the model reads and
    # recovers from. Assert on the message, not just is_error — a bare "Error
    # executing tool" means the tool raised something other than ToolError and
    # its message was silently dropped.
    r = await client.call_tool("read_file", {"name": "does-not-exist.txt"})
    msg = r.content[0].text if r.content else ""
    check("a missing file is flagged as an error", r.is_error, repr(msg))
    check("the error message reaches the caller intact", "does-not-exist.txt" in msg,
          f"got {msg!r} — if this is bare 'Error executing tool', the tool "
          f"raised something other than ToolError and its message was dropped")

    r = await client.call_tool("read_file", {"name": "../etc/passwd"})
    msg = r.content[0].text if r.content else ""
    check("a path outside the working directory is refused",
          r.is_error and "outside the working directory" in msg, repr(msg))

    r = await client.call_tool("read_file", {"name": "check-notes.txt", "start_line": 99})
    msg = r.content[0].text if r.content else ""
    check("reading past the end says how long the file is",
          r.is_error and "past the end" in msg, repr(msg))

    r = await client.call_tool("write_file", {"name": "check-notes.txt", "content": "x", "mode": "prepend"})
    msg = r.content[0].text if r.content else ""
    check("an unknown write mode is rejected by name", r.is_error and "prepend" in msg, repr(msg))

    r = await client.call_tool("write_file", {"name": "check-new.txt", "content": "x", "mode": "append"})
    msg = r.content[0].text if r.content else ""
    check("appending to a missing file explains how to create it",
          r.is_error and "check-new.txt" in msg, repr(msg))

    r = await client.call_tool("search_files", {"query": ""})
    msg = r.content[0].text if r.content else ""
    check("an empty search query is rejected", r.is_error and "must not be empty" in msg, repr(msg))


async def main() -> None:
    for artifact in ARTIFACTS:
        (WORK_DIR / artifact).unlink(missing_ok=True)

    # ---- Writer: holds both roles, so everything is allowed -------------
    as_identity("test-writer", [ROLE_READ, ROLE_WRITE])
    async with Client(mcp) as client:
        listing = await client.list_tools()
        names = [t.name for t in listing.tools]
        print("Tools:", names)
        check("every expected tool is registered",
              {"list_files", "file_info", "read_file", "write_file", "search_files"} <= set(names),
              f"got {names}")
        check("every tool has a description the model can read",
              all(t.description for t in listing.tools),
              f"missing: {[t.name for t in listing.tools if not t.description]}")
        await check_tool_behaviour(client)

    # ---- Reader: read tools allowed, write refused ----------------------
    as_identity("test-reader", [ROLE_READ])
    async with Client(mcp) as client:
        for tool, args in [
            ("list_files", {}),
            ("file_info", {"name": "check-notes.txt"}),
            ("read_file", {"name": "check-notes.txt"}),
            ("search_files", {"query": "alpha"}),
        ]:
            r = await client.call_tool(tool, args)
            check(f"reader may call {tool}", not r.is_error, str(r.content)[:160])

        await check_denied(client, "reader", "write_file",
                           {"name": "check-reader.txt", "content": "should never be written"},
                           ROLE_WRITE)
        check("the refused write left no file behind",
              not (WORK_DIR / "check-reader.txt").exists(),
              "write_file ran despite the denial")

    # ---- No identity: every guarded tool refuses ------------------------
    # This is what a caller hits when the token is valid but carries no roles.
    auth_context_var.set(None)
    async with Client(mcp) as client:
        for tool, args in [
            ("list_files", {}),
            ("file_info", {"name": "check-notes.txt"}),
            ("read_file", {"name": "check-notes.txt"}),
            ("search_files", {"query": "alpha"}),
            ("write_file", {"name": "check-reader.txt", "content": "x"}),
        ]:
            r = await client.call_tool(tool, args)
            msg = r.content[0].text if r.content else ""
            check(f"an unauthenticated caller is refused {tool}",
                  r.is_error and "not authenticated" in msg, repr(msg[:120]))

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
