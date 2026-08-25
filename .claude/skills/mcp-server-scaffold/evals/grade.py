#!/usr/bin/env python3
"""Grade one generated MCP server project against the assertions in evals.json.

Usage:  python grade.py <project-dir> <eval-id>

Prints JSON mapping each assertion to {"passed": bool, "evidence": str}. Only the
mechanically decidable assertions are covered; the ones about docstring quality
and whether the server instructions say anything useful need a reader.

Assertions that both a skill run and a no-skill baseline passed in every run of
iteration 1 were dropped — they measured the model's own MCP knowledge, not the
skill. See evals.json "notes".
"""

import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
eval_id = int(sys.argv[2])

py = sorted(root.rglob("*.py"))
src = {p: p.read_text(encoding="utf-8", errors="replace") for p in py}
allpy = "\n".join(src.values())

compose = [p for p in root.rglob("*") if p.name in
           ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")]
dockerfile = [p for p in root.rglob("*") if p.name.startswith("Dockerfile")]
tests = [p for p in py if "test" in p.name.lower()]
composetxt = "\n".join(p.read_text(errors="replace") for p in compose)
dockertxt = "\n".join(p.read_text(errors="replace") for p in dockerfile)
testtxt = "\n".join(p.read_text(errors="replace") for p in tests)
servers = [p for p in py if p not in tests and "agent" not in p.name.lower()]
servertxt = "\n".join(src[p] for p in servers)

R = {}
def check(text, passed, evidence):
    R[text] = {"passed": bool(passed), "evidence": evidence}


# ---- Discriminating in iteration 1 --------------------------------------

# Ignore asyncio.run / anyio.run — we want the server's own run() call.
run_call = None
for m in re.finditer(r"(?P<obj>[A-Za-z_][A-Za-z0-9_]*)\.run\((?P<args>[^)]*)\)", allpy, re.S):
    if m.group("obj") in ("asyncio", "anyio", "subprocess", "uvicorn"):
        continue
    if "transport" in m.group("args") or "port" in m.group("args"):
        run_call = m
        break
    run_call = run_call or m
ctor = re.search(r"MCPServer\((?P<args>(?:[^()]|\([^()]*\))*)\)", allpy, re.S)
bad_ctor = re.search(r"\b(host|port|transport)\s*=", ctor.group("args") if ctor else "")
check("Transport and networking arguments are passed to mcp.run(), not to the MCPServer constructor",
      run_call and re.search(r"transport\s*=|port\s*=", run_call.group("args")) and not bad_ctor,
      f"run() args: {run_call.group('args').strip()[:120]!r}" if run_call else "no server .run( call found")

prof = re.search(r"profiles:\s*\[?[^\n]*test", composetxt)
check("Compose has a profile-gated test service, so a plain `up` does not run the tests",
      bool(prof), f"match: {prof.group(0)!r}" if prof else "no test profile in compose")

copies_all = bool(re.search(r"(?:COPY|ADD)\s+\.\s", dockertxt))
named = [p.name for p in tests if p.name in dockertxt]
check("Dockerfile COPYs every runnable file that a compose service invokes, including the test script",
      copies_all or bool(named),
      "COPY . . (copies everything)" if copies_all else f"test scripts named in Dockerfile: {named}")

check("Test script checks is_error on a deliberately bad call instead of expecting a raised exception",
      "is_error" in testtxt,
      "is_error referenced in test script" if "is_error" in testtxt else "no is_error reference")

hc = "\n".join(v for k, v in src.items() if "health" in k.name.lower())
hc_tcp = "create_connection" in hc or "socket" in hc
hc_http = bool(re.search(r"urlopen|requests\.get|httpx\.get|curl", hc + composetxt))
check("Healthcheck checks that the TCP port accepts a connection rather than making an HTTP GET to /mcp",
      hc_tcp and not hc_http,
      f"tcp-style: {hc_tcp}, http-style: {hc_http}" + ("" if hc else " (no healthcheck script found)"))


# ---- The ToolError trap, found by iteration 1 ---------------------------
# The costliest defect this eval catches: a tool that raises anything other than
# ToolError has its message replaced by "Error executing tool <name>", so the
# model is told a call failed and given no reason. It fails silently, which is
# why it needs its own assertion rather than trusting is_error.

imports_toolerror = bool(re.search(r"from\s+mcp\.server\.mcpserver\.exceptions\s+import[^\n]*ToolError", servertxt))
bare_raises = re.findall(r"raise\s+(ValueError|RuntimeError|KeyError|Exception)\(", servertxt)
check("Tools raise ToolError from mcp.server.mcpserver.exceptions, so the failure message actually "
      "reaches the model instead of being replaced by \"Error executing tool <name>\"",
      imports_toolerror and not bare_raises,
      f"ToolError imported: {imports_toolerror}; bare raises that would be swallowed: {bare_raises or 'none'}")

# A test that only asserts is_error cannot tell a good error from a swallowed one.
asserts_text = bool(re.search(r"in\s+msg\b|in\s+text\b|in\s+err\w*\b|content\[0\]\.text[^\n]*(?:in|==)|"
                             r"(?:in|==)[^\n]*content\[0\]\.text", testtxt))
check("The test asserts on the error message text, not only on is_error, so a swallowed message is caught",
      asserts_text,
      "test compares error message text" if asserts_text else "test only checks is_error, so a swallowed message would pass")


# ---- Kept as regression guards despite not discriminating ---------------

if eval_id == 0:
    conf = re.search(r"\.resolve\(\)", allpy) and re.search(
        r"is_relative_to|\.parent\s*!=|\.parent\s*==|startswith\(|\.parents\b", allpy)
    check("File access is confined to one directory: paths are resolved and anything outside is refused",
          bool(conf), "resolve() plus a containment comparison" if conf else "no resolve()+containment check found")
    vol = re.search(r"-\s*(?:\$\{[A-Z_]+:-)?\.?/[^\s:]*:/", composetxt)
    check("Compose mounts the shared PDF folder as a host volume, so files on the host are visible to the tools",
          bool(vol), f"match: {vol.group(0).strip()!r}" if vol else "no host bind mount in compose")

if eval_id == 1:
    vol = re.search(r"-\s*(?:\$\{[A-Z_]+:-)?\.?/[^\s:]*:/", composetxt)
    check("No filesystem working directory and no volume mount, since the server wraps an API",
          not vol, "no host bind mount" if not vol else f"found mount: {vol.group(0).strip()!r}")
    tok = re.search(r"environ(?:\.get)?\(\s*[\"'][A-Z_]*(TOKEN|PAT|GITHUB)[A-Z_]*[\"']", allpy)
    hard = re.search(r"gh[pousr]_[A-Za-z0-9]{20,}", allpy)
    check("The GitHub token is read from an environment variable and never hardcoded",
          bool(tok) and not hard, f"env read: {tok.group(0)!r}" if tok else "no env token read found")

print(json.dumps(R, indent=2))
