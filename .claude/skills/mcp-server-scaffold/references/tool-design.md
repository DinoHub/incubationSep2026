# Designing tools a model uses correctly

A tool's signature and docstring are its entire interface to the model. There is
no separate documentation the model consults and no negotiation — it reads the
name, the description, and the parameter schema, then decides. Most bad MCP
experiences trace back to a tool that was described vaguely, so the model called
the wrong one, or called the right one with wrong arguments.

## The docstring is the description

The SDK uses the docstring as the tool description the model sees. Say what the
tool does and how each parameter behaves.

```python
# Vague — the model has to guess what radius does.
"""Blur an image."""

# Useful — it now knows both what happens and which direction to move radius.
"""Apply a Gaussian blur. Larger radius = blurrier."""
```

Ordering constraints belong here too, or in the server-level `instructions`:
"Call `list_images` to see what is available and `image_info` to check
dimensions before cropping." A model that does not know a discovery tool exists
will guess filenames.

## Type hints are the schema

The SDK generates JSON Schema from the signature. You never write one by hand.

```python
@mcp.tool()
def crop(name: str, left: int, top: int, right: int, bottom: int,
         output: str | None = None) -> ImageResult:
```

This gives the model six typed parameters, five required and one optional. Two
consequences worth internalizing:

- **Annotate everything.** An unannotated parameter loses its type in the
  schema, and the model starts passing strings where you wanted integers.
- **Defaults communicate.** `radius: float = 2.0` tells the model there is a
  sensible normal value, which stops it from inventing extreme ones.

## Return a model when the result gets used

Returning a Pydantic `BaseModel` gives the host a schema and parseable
structured content instead of text a caller has to scrape.

```python
class ImageResult(BaseModel):
    output: str   # filename of the new image
    width: int
    height: int
```

The payoff shows up in chained calls: a tool that returns `output` as a named
field makes it far more likely the model feeds that filename into the next call.
Plain types (`str`, `int`, `list[str]`) are the right choice for simple tools —
`list_images() -> list[str]` needs no wrapper.

## Raise ToolError, not ValueError

A tool that fails should hand the model something it can act on. In SDK v2 only
one exception does that: `ToolError`. Everything else is caught and re-raised as
`UnexpectedToolError`, and the caller receives the bare string
`Error executing tool <name>` with your message discarded.

```python
from mcp.server.mcpserver.exceptions import ToolError   # not exported from mcp or mcp.server

if not p.exists():
    raise ToolError(f"No such file: {name!r}. Call list_files to see what's there.")
```

```python
# What the caller actually receives:
raise ValueError("No such file: 'cat.png'. Call list_files.")
#   -> is_error=True, content: "Error executing tool read_file"      message gone

raise ToolError("No such file: 'cat.png'. Call list_files.")
#   -> is_error=True, content: "Error executing tool read_file: No such file:
#      'cat.png'. Call list_files."                                  message kept
```

This is worth being deliberate about, because the failure is quiet: the call is
still marked as an error, the server does not crash, and nothing in the logs
says the message was dropped. The tool just becomes useless for recovery — the
model knows *that* it failed and has no idea *why*. A test that asserts the
message text is present, rather than only that `is_error` is true, is what
catches it.

The wrapping is not a wart to route around everywhere. It is the right default
for genuine bugs, where a raw `KeyError` or a traceback would leak internals to
the model without helping it. So the split is: anticipated, actionable failures
get `ToolError` with a message written for a reader who will retry; unexpected
ones you let propagate and get wrapped.

Either way, do not return an error as a normal value. A tool that returns the
string `"error: bad input"` looks like a success to the caller, and the model
will treat it as one.

## Confine filesystem access

If tools touch files, resolve every path against one directory and refuse
anything that escapes it. This is not defensive politeness — without it, a model
that has been talked into reading `../../.ssh/id_rsa` will do exactly that.

```python
def _resolve(name: str) -> Path:
    p = (WORK_DIR / name).resolve()
    if p.parent != WORK_DIR:
        raise ValueError(f"{name!r} is outside the working directory.")
    return p
```

Resolve first, then compare — checking the string before resolution misses
`..` traversal and symlinks. Comparing `p.parent` to the directory also rules
out subdirectories, which is usually what you want; if you need nesting, use
`p.is_relative_to(WORK_DIR)` instead and accept the wider surface.

## Sizing the tool set

Prefer a handful of tools that each do one thing over one tool with a `mode`
parameter. The model picks by reading descriptions, and a discriminating name
plus a specific docstring beats a switch it has to reason about. That said, a
server with forty near-identical tools dilutes every description; if you get
there, group them behind a smaller number of parameterized tools and say in the
docstring which values are valid.

Include a read-only discovery tool whenever the tools operate on named things —
`list_files`, `list_tables`, `list_projects`. Without one, the model's only
option is to guess names and recover from errors, which costs turns.

## Resources and prompts

Tools are the common case, but the protocol has two more primitives:

- **Resources** expose read-only data at a URI the host can fetch without
  spending a model turn — a config file, a schema, a record. Reach for one when
  the host should be able to load context directly rather than asking the model
  to call something.
- **Prompts** are reusable, parameterized message templates the host can offer
  the user, often as a slash command.

Both are commented out in the generated server module. Uncomment when you have a
real use; an empty resource adds noise to the listing.
