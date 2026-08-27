#!/usr/bin/env python3
"""Write a complete, runnable MCP server project from the bundled templates.

The point of doing this in a script rather than by hand is that eight of the
nine files are pure boilerplate that never changes between projects. Generate
them, then spend your attention on the one file that matters — the tools.

Example:

    python scaffold.py --name "ImageTools" --dir ./image-tools \
        --workdir images --deps "Pillow>=11"

Every generated file is listed on stdout. Nothing is overwritten unless you
pass --force.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

IF_WORKDIR = "# {{IF_WORKDIR}}"
END_WORKDIR = "# {{END_WORKDIR}}"


def snake(name: str) -> str:
    """"ImageTools" -> "image_tools"; "image-tools" -> "image_tools"."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    return re.sub(r"_+", "_", s).strip("_").lower()


def kebab(name: str) -> str:
    return snake(name).replace("_", "-")


def strip_conditionals(text: str, keep: bool) -> str:
    """Handle the {{IF_WORKDIR}} / {{END_WORKDIR}} line markers.

    keep=True drops just the marker lines; keep=False drops the block too. Line
    markers rather than inline ones keep the templates readable as real files.
    """
    out, inside = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == IF_WORKDIR:
            inside = True
            continue
        if stripped == END_WORKDIR:
            inside = False
            continue
        if inside and not keep:
            continue
        out.append(line)
    if inside:
        raise ValueError("unterminated {{IF_WORKDIR}} block in template")
    return "".join(out)


def render(template: str, subs: dict[str, str], workdir: bool) -> str:
    text = (ASSETS / template).read_text(encoding="utf-8")
    text = strip_conditionals(text, keep=workdir)
    for key, value in subs.items():
        text = text.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if leftover:
        raise ValueError(f"{template}: unsubstituted placeholders {sorted(set(leftover))}")
    return text


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True,
                   help='Server name the model sees, e.g. "ImageTools".')
    p.add_argument("--dir", required=True,
                   help="Directory to write the project into. Created if absent.")
    p.add_argument("--module",
                   help="Server module stem. Default: <snake_name>_server.")
    p.add_argument("--workdir", default="data", metavar="NAME",
                   help="Name of the one directory the tools may touch (default: data). "
                        "Mounted from the host and confined by a path check.")
    p.add_argument("--no-workdir", action="store_true",
                   help="For a server with no filesystem of its own — an API or "
                        "database wrapper. Omits the working directory, its mount, "
                        "the path-confinement helpers, and seed_data.py.")
    p.add_argument("--port", default="8000", help="Host and container port (default: 8000).")
    p.add_argument("--deps", default="",
                   help='Extra pip requirements, comma-separated, e.g. "Pillow>=11,httpx>=0.27".')
    p.add_argument("--force", action="store_true", help="Overwrite existing files.")
    args = p.parse_args()

    workdir = not args.no_workdir
    module = args.module or f"{snake(args.name)}_server"
    extra = "\n".join(d.strip() for d in args.deps.split(",") if d.strip())

    subs = {
        "SERVER_NAME": args.name,
        "MODULE": module,
        "IMAGE_NAME": f"mcp-{kebab(args.name)}",
        "URI_SCHEME": kebab(args.name),
        # Name to register the server under in an MCP host, e.g. "image-tools".
        "SLUG": kebab(args.name),
        "PORT": str(args.port),
        "EXTRA_DEPS": extra,
        "WORK_DIR": args.workdir if workdir else "",
        "WORK_DIR_ENV": f"{snake(args.workdir).upper()}_DIR" if workdir else "",
    }

    plan = {
        f"{module}.py": "server_workdir.py.tmpl" if workdir else "server_plain.py.tmpl",
        "test_server.py": "test_workdir.py.tmpl" if workdir else "test_plain.py.tmpl",
        "http_server.py": "http_server.py.tmpl",
        "healthcheck.py": "healthcheck.py.tmpl",
        "requirements.txt": "requirements.txt.tmpl",
        "Dockerfile": "Dockerfile.tmpl",
        "docker-compose.yaml": "docker-compose.yaml.tmpl",
        "README.md": "README.md.tmpl",
    }
    if workdir:
        plan["seed_data.py"] = "seed_data.py.tmpl"

    root = Path(args.dir).resolve()
    existing = [name for name in plan if (root / name).exists()]
    if existing and not args.force:
        print(f"Refusing to overwrite in {root}: {', '.join(sorted(existing))}", file=sys.stderr)
        print("Pass --force to overwrite, or pick another --dir.", file=sys.stderr)
        return 1

    root.mkdir(parents=True, exist_ok=True)
    rendered = {name: render(tmpl, subs, workdir) for name, tmpl in plan.items()}
    for name, text in sorted(rendered.items()):
        (root / name).write_text(text, encoding="utf-8")
        print(f"wrote {root / name}")

    if workdir:
        (root / args.workdir).mkdir(exist_ok=True)
        print(f"wrote {root / args.workdir}/ (working directory, mounted into the container)")

    print(f"\nNext: edit {module}.py — replace the example tools with the real ones.")
    print("Then: docker compose build && docker compose run --rm test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
