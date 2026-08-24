"""General template for an MCP server.

Copy this file, rename it, and fill in the pieces marked TODO. See
writing-an-mcp-server.md for the full walkthrough and API notes (v1 vs v2,
transports, etc).

Run it interactively:   mcp dev mcp_template.py
Run it directly:        python mcp_template.py   (stdio transport)
"""

from pydantic import BaseModel

from mcp.server import MCPServer

mcp = MCPServer(
    "TemplateServer",  # TODO: name the server
    instructions=(
        # TODO: tell the model when/how to use these tools. This is the
        # first thing the model reads, so be concrete about ordering
        # ("call X before Y") and constraints.
        "Describe what this server is for and how its tools should be used."
    ),
)


# ---- Models -----------------------------------------------------------
# Structured return types make tool output predictable and self-documenting.
# Plain types (str, int, list[str], ...) work fine too for simple tools.

class ExampleResult(BaseModel):
    """What example_tool returns."""

    ok: bool
    message: str


# ---- Tools ----------------------------------------------------------------
# A tool is any function decorated with @mcp.tool(). The docstring becomes
# the tool description the model sees, and the signature (with type hints)
# becomes its input schema — keep both accurate and specific.

@mcp.tool()
def example_tool(input: str, flag: bool = False) -> ExampleResult:
    """TODO: describe what this tool does, and when the model should call it.

    Raise ValueError with a clear message for bad input — MCP surfaces it to
    the model as a tool error it can react to, rather than crashing the server.
    """
    if not input:
        raise ValueError("input must not be empty.")
    # TODO: do the actual work here.
    return ExampleResult(ok=True, message=f"processed {input!r} (flag={flag})")


@mcp.tool()
def another_tool() -> list[str]:
    """TODO: a second example — tools can return plain types too, not just models."""
    return ["TODO", "replace", "with", "real", "output"]


# ---- Resources --------------------------------------------------------
# Resources expose read-only data at a URI the host can fetch without a
# model turn (e.g. for context injection). Uncomment and adapt as needed.

# @mcp.resource("template://info")
# def server_info() -> str:
#     """Static info about this server."""
#     return "TODO: resource content"


# ---- Prompts ------------------------------------------------------------
# Prompts are reusable, user-triggered message templates the host can offer
# (e.g. as a slash command). Uncomment and adapt as needed.

# @mcp.prompt()
# def example_prompt(topic: str) -> str:
#     """TODO: describe when a user would pick this prompt."""
#     return f"TODO: prompt text about {topic}"


if __name__ == "__main__":
    mcp.run()  # stdio by default; see http_server.py for streamable-http
