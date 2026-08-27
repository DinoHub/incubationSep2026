"""DocTools — an MCP server for reading, writing, and searching text documents.

Every tool works inside one directory (documents/). Confining paths to a single
folder is what stops a model from reading or writing arbitrary files, so keep
that shape if you add tools.

Run over stdio:            python doc_tools_server.py
Run over Streamable HTTP:  python http_server.py
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from mcp.server import MCPServer

# ToolError is the one exception whose message reaches the model. Anything else
# is wrapped as "Error executing tool <name>" with your text withheld, so use
# this for every failure the model is meant to read and recover from. It lives
# only on this path — it is not re-exported from mcp or mcp.server.
from mcp.server.mcpserver.exceptions import ToolError

# Authentication (is this a real token?) is checked by the verifier during the
# connection handshake, before any tool is reachable. Authorization (may this
# caller run this tool?) is checked per call by require_role below.
from auth import JWKSTokenVerifier, auth_settings, require_role

ROLE_READ = "documents:read"
ROLE_WRITE = "documents:write"

# The one directory every tool is allowed to touch.
WORK_DIR = Path(os.environ.get("DOCUMENTS_DIR", "documents")).resolve()
WORK_DIR.mkdir(parents=True, exist_ok=True)

mcp = MCPServer(
    "DocTools",
    instructions=(
        "DocTools reads, writes, and searches plain text documents kept in one "
        "working directory. It cannot reach any file outside that directory.\n"
        "\n"
        "Start with list_files to see what exists — filenames are not guessable "
        "and a wrong guess costs a turn. Call file_info before read_file on "
        "anything you have not read yet: read_file returns a window of lines, "
        "not the whole document, and file_info tells you how many lines there "
        "are so you can page through a long one. To find something when you do "
        "not know which file holds it, use search_files, which reports the "
        "filename and line number of every match; then read_file around that "
        "line.\n"
        "\n"
        "write_file replaces a whole file by default. To add to an existing "
        "document without losing it, pass mode=\"append\".\n"
        "\n"
        "Every tool requires a role, carried by your bearer token. list_files, "
        "file_info, read_file, and search_files each need documents:read. "
        "write_file needs documents:write. A call made without the role it "
        "needs comes back as an error naming the missing role; retrying it "
        "will not help, so report it instead."
    ),
    token_verifier=JWKSTokenVerifier(),
    auth=auth_settings(),
)


# ---- Structured return types ---------------------------------------------
# Returning a BaseModel hands the host a schema and parseable structured
# content instead of a wall of text, which also makes it far likelier that a
# filename from one call is fed correctly into the next.

class FileInfo(BaseModel):
    """Metadata about one file. No content."""

    name: str
    size_bytes: int
    line_count: int
    modified: str  # ISO 8601, UTC


class FileContent(BaseModel):
    """A window of lines from one file."""

    name: str
    start_line: int      # 1-based line number of the first line returned
    end_line: int        # 1-based line number of the last line returned; 0 if empty
    total_lines: int     # lines in the whole file
    truncated: bool      # True when lines after end_line were not returned
    text: str            # the returned lines, newline-joined


class Match(BaseModel):
    """One matching line found by search_files."""

    name: str
    line_number: int     # 1-based
    line: str


# ---- Helpers --------------------------------------------------------------

def _resolve(name: str) -> Path:
    """Resolve a name to a path, refusing anything outside WORK_DIR."""
    if not name.strip():
        raise ToolError("name must not be empty. Call list_files to see the available files.")
    p = (WORK_DIR / name).resolve()
    if p.parent != WORK_DIR:
        raise ToolError(
            f"{name!r} is outside the working directory. Pass a plain filename "
            f"with no directory part, as returned by list_files."
        )
    return p


def _require_file(name: str) -> Path:
    """Resolve a name and insist the file exists."""
    p = _resolve(name)
    if not p.is_file():
        raise ToolError(f"No such file: {name!r}. Call list_files to see what's there.")
    return p


def _read_lines(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def _info(p: Path) -> FileInfo:
    stat = p.stat()
    return FileInfo(
        name=p.name,
        size_bytes=stat.st_size,
        line_count=len(_read_lines(p)),
        modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
    )


# ---- Tools ----------------------------------------------------------------
# The type hints ARE the input schema — the SDK generates it, so you never
# hand-write JSON Schema. The docstring is what the model reads to decide
# whether to call a tool, so say what it does and how each parameter behaves.

@mcp.tool()
def list_files() -> list[str]:
    """List the names of every file in the working directory, sorted.

    Call this first. Filenames from here are the only valid input to the other
    tools, which take a plain filename with no directory part.
    """
    require_role(ROLE_READ)
    return sorted(p.name for p in WORK_DIR.iterdir() if p.is_file())


@mcp.tool()
def file_info(name: str) -> FileInfo:
    """Report a file's size, line count, and last-modified time without reading it.

    Use this before read_file to find out how many lines a document has, so you
    know whether one read_file call will cover it.
    """
    require_role(ROLE_READ)
    return _info(_require_file(name))


@mcp.tool()
def read_file(name: str, start_line: int = 1, max_lines: int = 200) -> FileContent:
    """Read a window of lines from a text file.

    start_line is the 1-based line to start at; max_lines is how many lines to
    return from there. The default window covers most short documents in one
    call. When the returned `truncated` field is true there are more lines after
    `end_line`, so call again with start_line set to end_line + 1 to continue.
    Check file_info first if you do not know the document's length.
    """
    require_role(ROLE_READ)
    if start_line < 1:
        raise ToolError(f"start_line must be 1 or greater, got {start_line}. Lines are numbered from 1.")
    if max_lines < 1:
        raise ToolError(f"max_lines must be 1 or greater, got {max_lines}.")

    p = _require_file(name)
    lines = _read_lines(p)
    total = len(lines)

    if start_line > total:
        raise ToolError(
            f"start_line {start_line} is past the end of {name!r}, which has "
            f"{total} line(s). Call file_info to check the length."
        )

    window = lines[start_line - 1 : start_line - 1 + max_lines]
    end_line = start_line + len(window) - 1 if window else 0
    return FileContent(
        name=p.name,
        start_line=start_line,
        end_line=end_line,
        total_lines=total,
        truncated=end_line < total,
        text="\n".join(window),
    )


@mcp.tool()
def write_file(name: str, content: str, mode: str = "overwrite") -> FileInfo:
    """Write text to a file in the working directory and return its new metadata.

    mode must be either "overwrite", which replaces the whole file and creates
    it if absent, or "append", which adds content to the end of an existing
    file. Appending starts the content on a new line if the file does not
    already end with one. Overwriting an existing file discards it, so read it
    first if you need what was there.
    """
    require_role(ROLE_WRITE)
    if mode not in ("overwrite", "append"):
        raise ToolError(f'mode must be "overwrite" or "append", got {mode!r}.')

    p = _resolve(name)
    if mode == "append":
        if not p.is_file():
            raise ToolError(
                f"Cannot append to {name!r}: no such file. Call list_files to "
                f'see what exists, or write it with mode="overwrite" to create it.'
            )
        existing = p.read_text(encoding="utf-8", errors="replace")
        separator = "" if (not existing or existing.endswith("\n")) else "\n"
        p.write_text(existing + separator + content, encoding="utf-8")
    else:
        p.write_text(content, encoding="utf-8")
    return _info(p)


@mcp.tool()
def search_files(query: str, case_sensitive: bool = False, max_results: int = 50) -> list[Match]:
    """Find every line containing query across all files in the working directory.

    query is matched as plain text, not a regular expression. Matching ignores
    case unless case_sensitive is true. Each result gives the filename and
    1-based line number, so pass them to read_file to see the surrounding text.
    At most max_results matches come back; narrow the query if you hit the cap.
    """
    require_role(ROLE_READ)
    if not query:
        raise ToolError("query must not be empty. Pass the text to search for.")
    if max_results < 1:
        raise ToolError(f"max_results must be 1 or greater, got {max_results}.")

    needle = query if case_sensitive else query.lower()
    matches: list[Match] = []
    for p in sorted(WORK_DIR.iterdir()):
        if not p.is_file():
            continue
        for number, line in enumerate(_read_lines(p), start=1):
            haystack = line if case_sensitive else line.lower()
            if needle in haystack:
                matches.append(Match(name=p.name, line_number=number, line=line))
                if len(matches) >= max_results:
                    return matches
    return matches


# ---- Resources ------------------------------------------------------------
# Read-only context the host can fetch at a URI without spending a model turn.
# Uncomment and adapt if you need it.

# @mcp.resource("doc-tools://info")
# def server_info() -> str:
#     """Static information about this server."""
#     return "TODO: resource content"


# ---- Prompts --------------------------------------------------------------
# Reusable, parameterized message templates the host can offer the user, often
# as a slash command. Uncomment and adapt if you need it.

# @mcp.prompt()
# def example_prompt(topic: str) -> str:
#     """TODO: describe when a user would reach for this prompt."""
#     return f"TODO: prompt text about {topic}"


if __name__ == "__main__":
    mcp.run()  # stdio by default
