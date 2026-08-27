# Writing Skills for Agents

This guide is about writing **agent skills**: the folders of instructions,
scripts, and reference material that turn a general-purpose coding agent into a
specialist at one task. It builds a real skill from an empty directory, then
compares the three ecosystems that have converged on this idea — Anthropic's
**Agent Skills**, **Cursor rules**, and OpenAI **Codex's `AGENTS.md`** — so a
skill you write reads the same way to whichever agent picks it up.

The rules, field names, and numbers here were checked against the current
Anthropic Agent Skills docs, the Claude Code skills docs, the Cursor rules docs,
and the `agents.md` / OpenAI Codex docs as of **August 2026**. Sources are listed
at the end.

## Contents

**Getting started**
- [Checklist](#checklist) — the whole guide in one page

**Foundations**
- [The one idea everything else follows from](#the-one-idea-everything-else-follows-from)
- [Anatomy of a `SKILL.md`](#anatomy-of-a-skillmd)

**Authoring best practices**
- [Writing the description](#writing-the-description--the-highest-leverage-part-of-the-whole-skill)
- [Keep the body concise](#keep-the-body-concise--context-is-a-public-good)
- [Match freedom to the fragility of the task](#match-the-level-of-freedom-to-the-fragility-of-the-task)
- [Progressive disclosure in practice](#progressive-disclosure-in-practice)
- [Workflows and feedback loops](#workflows-and-feedback-loops)
- [A few reusable patterns](#a-few-reusable-patterns)
- [Content hygiene](#content-hygiene)

**Putting it into practice**
- [Build one end to end](#build-one-end-to-end)
- [Test and iterate](#test-and-iterate--the-part-people-skip)

**Beyond a single skill**
- [The wider ecosystem: Cursor & Codex](#the-wider-ecosystem-same-idea-three-dialects)
- [Surface differences that bite](#surface-differences-that-bite)
- [Security: skills are executable trust](#security-skills-are-executable-trust)

**Reference**
- [Sources](#sources)

## Checklist

The whole guide compressed to one page — verify each item before you call a skill
done. Every section below explains the *why* behind these lines.

**Discovery & structure**
- [ ] `description` is third-person, specific, and says both *what* and *when*, with real trigger terms
- [ ] `name` is a gerund (or clean noun phrase), lowercase-hyphenated, ≤ 64 chars, no reserved words
- [ ] `SKILL.md` body is under 500 lines
- [ ] Reference files are one level deep from `SKILL.md`
- [ ] Reference files > 100 lines start with a table of contents
- [ ] Files named for their content; forward slashes only

**Content quality**
- [ ] Concise — no explanations of things the model already knows
- [ ] Freedom matched to fragility (prose for open tasks, exact commands for fragile ones)
- [ ] Consistent terminology; no time-sensitive claims in the main flow
- [ ] One clear default per decision, not a menu of options
- [ ] Multi-step tasks have a checklist; quality-critical ones have a validate→fix→repeat loop

**Scripts (if any)**
- [ ] Scripts solve errors rather than defer them; no unexplained magic numbers
- [ ] Body makes execute-vs-read intent explicit
- [ ] Required packages named; no assumption they're installed; works within the target surface's constraints

**Testing**
- [ ] ~3 evaluations written (ideally before the docs)
- [ ] Tested on real tasks, and observed how the agent navigates the files
- [ ] Tested across every model you'll run it on

## The one idea everything else follows from

An agent has a fixed context window, and it is shared by the system prompt, the
conversation so far, every other skill's metadata, and the user's actual
request. A skill is not "more prompt you always pay for." A well-built skill
costs almost nothing until the moment it is relevant, and then loads only the
part that is relevant.

Anthropic calls the mechanism **progressive disclosure**, and it is the single
idea that governs every authoring decision below. Content loads in three levels:

| Level | What | When it loads | Token cost |
| --- | --- | --- | --- |
| **1 — Metadata** | `name` + `description` from the YAML frontmatter | Always, at startup, for *every* installed skill | ~100 tokens per skill |
| **2 — Instructions** | The body of `SKILL.md` | Only when the skill is triggered | Aim for under 5k tokens |
| **3 — Resources** | Bundled files: extra `.md` references, scripts, data | Only when the body points the agent at them | Zero until read; a script's *code* never enters context — only its output |

Read that table twice. It explains why the `description` is the most important
64–1024 characters you will write (it is the only thing loaded for a skill that
is *not* active, so it is what the agent routes on), why the body should stay
short (it competes with the live conversation once loaded), and why you can
bundle a 2,000-line API reference without guilt (it costs nothing until the
agent reads it).

The mental model Anthropic recommends: **a skill is the onboarding guide you'd
write for a competent new teammate.** The front page (`SKILL.md`) is a short
orientation that says what this is and points to where the details live. Nobody
reads the whole binder on day one; they read the page they need when they need
it. Build the skill the same way.

### Where a skill sits next to the other options

- A **prompt** is a one-off instruction for the current conversation. A skill is
  a prompt you'd otherwise paste repeatedly, promoted to a reusable, on-demand
  resource.
- **MCP** (see the `1_mcp_tutorial`) gives an agent *new actions* — live data,
  API calls, side effects. A skill gives it *know-how*: which action to take,
  in what order, with what conventions. They compose: a skill can tell the agent
  which MCP tools to call and in what sequence.
- A **subagent** is a separate context that runs a delegated task. A skill can be
  told to run in one, but a skill itself is just knowledge, not a process.

Rule of thumb from the Claude Code docs: *create a skill when you keep pasting
the same instructions, checklist, or procedure into chat — or when a section of
your `CLAUDE.md` has grown from a fact into a procedure.* Facts belong in
`CLAUDE.md`/`AGENTS.md` (always loaded). Procedures belong in a skill (loaded on
demand).

## Anatomy of a `SKILL.md`

Every skill is a directory whose entry point is a file named `SKILL.md`. The
directory name is the skill's identity (and, in Claude Code, the `/command` you
type). The file is YAML frontmatter followed by a Markdown body:

```markdown
---
name: reviewing-python
description: Reviews Python diffs for correctness, style, and security issues. Use when the user asks for a code review of Python changes, mentions reviewing a PR or diff, or asks whether Python code is ready to merge.
---

# Reviewing Python

## Instructions
[step-by-step guidance the agent follows]

## Examples
[concrete input/output pairs]
```

### Frontmatter: the required two fields

Only `name` and `description` are required, and both have hard validation rules
enforced by the platform:

| Field | Rules |
| --- | --- |
| `name` | ≤ 64 characters; lowercase letters, numbers, and hyphens only; no XML tags; cannot contain the reserved words `anthropic` or `claude`. |
| `description` | Non-empty; ≤ 1,024 characters; no XML tags; must say **both what the skill does and when to use it**. |

**Name it in gerund form** (verb + *-ing*) — `processing-pdfs`,
`analyzing-spreadsheets`, `writing-documentation`. Noun phrases (`pdf-processing`)
and action forms (`process-pdfs`) are acceptable; vague names (`helper`, `utils`,
`tools`, `data`) are not. Consistent naming is what lets you scan a library of
50 skills and know what each does at a glance.

> In **Claude Code** specifically, a personal/project skill's directory name is
> what you invoke (`/reviewing-python`); the `name:` field there only sets the
> display label. Claude Code also accepts optional extension fields covered in
> the [Claude Code extensions](#claude-code-extensions) section. Keep to `name`
> and `description` if you want the skill to load unchanged on claude.ai and
> through the API, which validate against the six-field open spec.

## Writing the description — the highest-leverage part of the whole skill

The `description` is the only thing an agent sees for a skill that isn't active
yet. Faced with a request and 100+ installed skills, the agent reads nothing but
these one-liners to decide which skill to pull in. A vague description means a
good skill never fires; a precise one means it fires exactly when it should.

Three rules, all from the Anthropic best-practices doc:

1. **Write in the third person.** The description is injected into the system
   prompt; first/second person ("I can help you…", "You can use this to…")
   causes discovery problems. Say what the skill *does*.
2. **Include both halves: what it does *and* when to use it.** The "when" is
   where you list concrete triggers — file types, user phrasings, situations.
3. **Use specific key terms**, not generic ones. The agent is keyword-matching
   your request against these strings.

```yaml
# Good — what + when + trigger terms
description: Extracts text and tables from PDF files, fills forms, and merges documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.

# Good — names the file extensions that should trigger it
description: Analyzes Excel spreadsheets, creates pivot tables, generates charts. Use when analyzing Excel files, spreadsheets, tabular data, or .xlsx files.

# Bad — no "when", no trigger terms, agent can't route on it
description: Helps with documents
```

Look back at the two real skills in this repo (`3_mcp_skills/*/SKILL.md`): each
description is a long, deliberate list of the phrasings and situations that
should trigger it ("even if they never say the word 'scaffold'"). That length is
not padding — it is the router's training data.

## Keep the body concise — context is a public good

Once the body loads, every token in it competes with the live conversation. The
default assumption should be: **the agent is already very smart.** Only add
context it doesn't already have. Challenge every paragraph — "Does the model
really need this? Can I assume it knows this? Does this sentence justify its
token cost?"

````markdown
<!-- Good (~50 tokens): assumes the model knows what a PDF is and how libraries work -->
## Extract PDF text
Use pdfplumber:
```python
import pdfplumber
with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```
````

```markdown
<!-- Bad (~150 tokens): three sentences explaining what a PDF is and that libraries exist -->
## Extract PDF text
PDF (Portable Document Format) files are a common file format that contains text,
images, and other content. To extract text you'll need a library. There are many
libraries available, but pdfplumber is recommended because it's easy to use...
```

Keep the `SKILL.md` body **under 500 lines**. Past that, the body has stopped
being an orientation and become the binder — split it (next section).

## Match the level of freedom to the fragility of the task

Not every instruction should be equally prescriptive. Anthropic frames this as
**degrees of freedom**, with a good analogy: think of the agent as a robot
walking a path.

- **Open field, no hazards → high freedom.** Many routes succeed; give direction
  and trust the model. Use prose steps. *Example: a code review, where the right
  emphasis depends on the code.*
  ```markdown
  ## Code review process
  1. Analyze the code structure and organization
  2. Check for potential bugs or edge cases
  3. Suggest improvements for readability and maintainability
  4. Verify adherence to project conventions
  ```
- **A preferred pattern exists → medium freedom.** Give a parameterized
  template or pseudocode and let the model adapt it.
- **Narrow bridge, cliffs either side → low freedom.** One safe sequence;
  fragile, high-stakes, must be consistent. Give the exact command and forbid
  improvisation. *Example: a database migration.*
  ````markdown
  ## Database migration
  Run exactly this script:
  ```bash
  python scripts/migrate.py --verify --backup
  ```
  Do not modify the command or add additional flags.
  ````

Getting this wrong in either direction hurts: over-constrain an open task and the
model fights the skill; under-constrain a fragile one and it improvises off the
cliff.

## Progressive disclosure in practice

When the body outgrows ~500 lines (or contains material only some tasks need),
move detail into bundled files and point at them from `SKILL.md`. A mature skill
looks like this:

```
reviewing-python/
├── SKILL.md              # orientation + the common path (loaded when triggered)
├── security.md           # deep dive, loaded only for security-focused reviews
├── style-guide.md        # the project's conventions, loaded as reference
└── scripts/
    ├── run_linters.sh     # executed, never read into context
    └── check_types.sh
```

Four rules make this work:

1. **Keep references one level deep.** Every reference file should link
   *directly* from `SKILL.md`. If `SKILL.md → advanced.md → details.md`, the
   agent tends to preview nested files with `head -100` instead of reading them
   whole, and gets partial information. Flat beats deep.
2. **Give reference files longer than ~100 lines a table of contents** at the
   top. When the agent previews rather than fully reads, the TOC still tells it
   the full scope of what's in the file.
3. **Organize by domain** so an irrelevant domain never loads. A BigQuery skill
   with `reference/finance.md`, `reference/sales.md`, `reference/product.md`
   lets a question about revenue pull in only `finance.md`. Point the agent at a
   `grep` line for large references so it can jump to the metric it needs.
4. **Name files for their content.** `form_validation_rules.md`, not `doc2.md`.
   The agent navigates the directory like a filesystem; descriptive names are how
   it decides what to open. Always use forward slashes, even for Windows
   (`scripts/helper.py`, never `scripts\helper.py`).

### Scripts: prefer them, and make them solid

A bundled script is often better than asking the agent to write the equivalent
code each time. It is **more reliable** (tested, deterministic), **cheaper** (its
code never enters context — only its output does), and **consistent** across
runs.

Two rules for scripts you ship:

- **Solve, don't defer.** Handle the error inside the script rather than letting
  it throw and hoping the agent recovers. A script that creates a missing file,
  or falls back to a default on a permission error, beats one that crashes and
  makes the agent guess.
- **No voodoo constants.** Every magic number gets a comment justifying it. *"If
  you don't know the right value, how will the agent?"*
  ```python
  # HTTP requests typically complete within 30s; longer allows for slow links
  REQUEST_TIMEOUT = 30
  # 3 retries balances reliability against latency; most flakes clear by retry 2
  MAX_RETRIES = 3
  ```

And **be explicit about intent** in the body — the agent needs to know whether a
file is to run or to read:

- *"Run `analyze_form.py` to extract the fields"* → execute.
- *"See `analyze_form.py` for the extraction algorithm"* → read as reference.

Finally, **don't assume packages are installed.** State the dependency and the
install command in the body. (On some surfaces the runtime has no network and no
runtime package installation — see [surface constraints](#surface-differences-that-bite).)

## Workflows and feedback loops

For anything multi-step, give the agent an explicit workflow — and for complex
ones, a checklist it can copy into its reply and tick off. This is what stops it
skipping a validation step.

````markdown
## PDF form-filling workflow
Copy this checklist and check off each item:
```
- [ ] Step 1: Analyze the form   (run analyze_form.py)
- [ ] Step 2: Map fields          (edit fields.json)
- [ ] Step 3: Validate the map    (run validate_fields.py)
- [ ] Step 4: Fill the form        (run fill_form.py)
- [ ] Step 5: Verify output        (run verify_output.py)
```
**Step 3 — Validate the map.** Run `python scripts/validate_fields.py fields.json`.
Fix every reported error before continuing.
````

The most valuable pattern layered on top is the **feedback loop**: *run a
validator → fix the errors it reports → repeat until clean → only then proceed.*
It works with a script (`validate.py`) or without one (a `STYLE_GUIDE.md` the
agent checks its draft against). For batch or destructive operations, extend it
to **plan → validate → execute**: have the agent write its intended changes to a
structured file, validate that file with a script, and only apply it once
validation passes. Errors get caught before anything is touched, and validator
messages should be verbose and specific — *"Field 'signature_date' not found.
Available fields: customer_name, order_total, signature_date_signed"* — so the
agent can actually fix them.

## A few reusable patterns

- **Template pattern.** Give the exact output shape. Signal strictness with your
  wording: *"ALWAYS use this exact template"* for an API/data format, or *"here's
  a sensible default, use your judgment"* when adaptation helps.
- **Examples pattern.** When quality depends on style (commit messages, release
  notes), show 2–3 input → output pairs. Examples convey tone and detail far
  better than description.
- **Conditional workflow.** Route the agent at a decision point: *"Creating new
  content? → Creation workflow. Editing existing? → Editing workflow."*

## Content hygiene

- **No time-sensitive information.** *"Before August 2025, use the old API"*
  silently rots. Put current guidance in the main flow and, if history matters,
  tuck the old way in a collapsed **"Old patterns"** section.
- **One term for one thing.** Pick "field" or "box", "extract" or "pull" — and
  use it throughout. Mixed vocabulary makes instructions harder to follow.
- **Don't offer five options.** *"Use pdfplumber for text extraction"* with a
  single escape hatch (*"for scanned PDFs needing OCR, use pdf2image"*) beats
  *"you could use pypdf, or pdfplumber, or PyMuPDF, or…"*.

## Build one end to end

Here's the whole arc on a small, real example: a skill that writes
[Conventional Commits](https://www.conventionalcommits.org) from your staged
diff. We'll grow it from a one-file skill into a progressively-disclosed one so
each level of the model shows up in practice. (Paths use the Claude Code
`.claude/skills/` convention — the same layout this repo's `3_mcp_skills` uses.)

### Step 1 — The minimal skill (Level 1 + 2 only)

```bash
mkdir -p .claude/skills/writing-conventional-commits
```

`.claude/skills/writing-conventional-commits/SKILL.md`:

````markdown
---
name: writing-conventional-commits
description: Writes a Conventional Commits message from staged git changes. Use when the user asks for a commit message, wants help committing, or asks how to describe their staged changes.
---

# Writing Conventional Commits

Generate one commit message for the staged changes, in Conventional Commits form.

## Format
`type(scope): summary` on the first line (≤ 50 chars, imperative mood), a blank
line, then a body explaining *why* the change was made. Types: `feat`, `fix`,
`docs`, `refactor`, `test`, `chore`.

## Examples
Input: Added JWT login endpoint and token-validation middleware
Output:
```
feat(auth): add JWT-based login

Add the login endpoint and middleware that validates bearer tokens on
each request, so protected routes reject unauthenticated callers.
```

Input: Fixed dates showing in the wrong timezone on reports
Output:
```
fix(reports): use UTC timestamps in report generation

Dates were rendered in server-local time; normalize to UTC so reports
read the same regardless of where they run.
```
````

That is a complete, useful skill. Its description carries the triggers; its body
is short and leans on examples (the right call for a style task — high freedom).

### Step 2 — Ground it in reality with a script (Level 3: execute)

The skill above hopes the agent already fetched the diff. Make that reliable by
having the skill pull the diff itself. Two ways, depending on the agent:

**Portable (any agent): a bundled script the body tells the agent to run.**

`.claude/skills/writing-conventional-commits/scripts/staged_diff.sh`:

```bash
#!/usr/bin/env bash
# Print staged changes only. Exit 0 with a marker if nothing is staged,
# so the skill can tell the user instead of inventing a message.
set -euo pipefail
if git diff --cached --quiet; then
  echo "__NO_STAGED_CHANGES__"
else
  git --no-pager diff --cached
fi
```

Add to the top of the body:

```markdown
## Get the changes
Run `bash scripts/staged_diff.sh`. If it prints `__NO_STAGED_CHANGES__`, tell the
user there is nothing staged and stop — do not write a message from unstaged work.
```

Note the script *solves rather than defers*: the empty case is handled in the
script with an unambiguous marker, not left for the agent to stumble into.

**Claude Code shortcut: dynamic context injection.** In Claude Code you can inline
a command's output into the body before the agent ever reads it, with a
`` !`…` `` line — no script file needed:

```markdown
## Current staged changes
!`git --no-pager diff --cached`
```

Claude Code runs the command and substitutes its output in place. Handy, but it's
a Claude-Code-only body feature — it won't do anything on claude.ai or via the API,
which is why the portable script version exists.

### Step 3 — Push the long stuff into a reference (Level 3: read)

If your team has real commit conventions — scope names, when to use `BREAKING
CHANGE:`, issue-linking rules — that's reference material most invocations don't
need inline. Put it in a sibling file with a TOC and link to it one level deep:

```markdown
## Conventions
Follow the house rules in [conventions.md](conventions.md) for scope names,
breaking-change footers, and issue links.
```

Now the model works as designed: metadata routes to the skill, the short body
loads on trigger, the script runs and only its *output* costs tokens, and
`conventions.md` loads only when a commit actually needs the detailed rules.

### Step 4 — Verify it, don't assume it

```bash
# In Claude Code: stage a change and invoke it directly
git add -p
# then, in the session:
/writing-conventional-commits
```

Or just describe your change (*"write me a commit message"*) and confirm the
skill fires on its own — that tests whether the **description** is doing its job,
which is the part most likely to be wrong.

## Test and iterate — the part people skip

A skill is only as good as its behavior on real tasks. Anthropic's guidance is
blunt about the order of operations:

**Build evaluations *before* writing extensive docs.** Otherwise you document
problems you imagined instead of ones the agent actually has. The loop:

1. Run the agent on representative tasks **without** the skill. Note the specific
   failures and missing context.
2. Write ~3 concrete evaluation scenarios that target those gaps. An eval is just
   a task + files + a rubric of expected behaviors:
   ```json
   {
     "skills": ["writing-conventional-commits"],
     "query": "Write a commit message for my staged changes",
     "expected_behavior": [
       "Runs the diff script and detects there ARE staged changes",
       "Produces a type(scope): summary first line under 50 characters",
       "Body explains why, not just what"
     ]
   }
   ```
   (There's no built-in runner for these — you grade them yourself. They're your
   source of truth for whether the skill works.)
3. Establish the baseline score without the skill.
4. Write the **minimum** instructions needed to pass — nothing more.
5. Iterate against the evals.

**Develop with one agent, test with another.** The most effective workflow uses
the model on both sides. Work with "Agent A" to *author and refine* the skill —
the model natively understands the skill format, so just ask it to write one and
to trim its own over-explanation (*"remove the paragraph defining what a win rate
is — the model already knows that"*). Then run "Agent B" — a fresh instance with
the skill loaded — on **real tasks, not test scenarios**. Watch what B actually
does, and bring specifics back to A: *"B forgot to filter test accounts even
though the skill mentions it — is that rule prominent enough?"* A might suggest
stronger wording (`MUST filter`, not `always filter`) or moving the rule up.

**Watch how the agent navigates.** Real usage reveals structure problems nothing
else will:

- Reads files in an order you didn't expect → your structure isn't as intuitive
  as you thought.
- Never follows a reference link → the link isn't prominent enough, or the file
  is unnecessary.
- Re-reads the same reference every time → that content probably belongs in
  `SKILL.md`.
- Fires when it shouldn't (or doesn't when it should) → fix the **description**
  first; that's the router.

**Test across every model you'll ship to.** A skill is an addition to a model, so
its effectiveness depends on the model. What's perfectly terse for Opus may be
too sparse for Haiku; what's right for Haiku may over-explain for Opus. If you
target several, aim for instructions that work for all of them.

## The wider ecosystem: same idea, three dialects

"Skills" is Anthropic's framing, but Cursor and OpenAI Codex have converged on
the same underlying move — *put durable, project-specific agent guidance in
version-controlled Markdown files instead of re-typing it* — with different
mechanics. Knowing all three lets you write guidance that travels.

### Cursor: rules (`.cursor/rules/*.mdc`)

Cursor's equivalent is **rules**, stored as `.mdc` files (Markdown + YAML
frontmatter) under `.cursor/rules/` and version-controlled. The defining feature
is that each rule declares *how it attaches*, via four types:

| Type | Attaches when | Frontmatter |
| --- | --- | --- |
| **Always** | Every request | `alwaysApply: true` |
| **Auto Attached** | A file matching a glob is in context | `globs: "src/**/*.tsx"`, `alwaysApply: false` |
| **Agent Requested** | The agent decides it's relevant, from the `description` | `description: "..."`, `alwaysApply: false` |
| **Manual** | Explicitly `@mentioned` | (no auto trigger) |

```md
---
alwaysApply: false
globs: src/components/**/*.tsx
description: Component standards for React
---
- Co-locate styles with the component.
- Prefer function components and hooks.
```

Note the parallels to skills: the `description` on an "Agent Requested" rule
plays exactly the role a skill's `description` does — it's what the model routes
on. Cursor's own best practices echo Anthropic's almost word for word: **keep
rules under 500 lines**, **reference files rather than pasting their contents**,
and **don't document what the model already knows** (*"use a linter instead"* of
a hand-written style rule). Cursor also reads nested `AGENTS.md` files for
granular, directory-scoped instructions.

### OpenAI Codex (and the cross-tool standard): `AGENTS.md`

`AGENTS.md` is *"a README for agents"* — one predictable Markdown file for the
context an agent needs that would clutter a human README. It's a deliberately
minimal, open format (plain Markdown, any headings you like) adopted across
Codex, Cursor, Jules, Zed, and others, and Claude Code reads it too. Recommended
sections: project overview, **build and test commands**, code style, testing
instructions, security considerations, PR/commit conventions, deployment steps.

Two mechanics matter:

- **Nesting and precedence.** Drop an `AGENTS.md` in each package of a monorepo.
  The agent reads the **nearest** file in the directory tree and the closest one
  wins. Codex builds one combined instruction set by concatenating from the Git
  root downward — global (`~/.codex/AGENTS.md`) first, then each directory level —
  so *files closer to the working directory override earlier guidance because
  they appear later in the prompt.* There's also a size budget (Codex defaults to
  a 32 KiB combined cap, `project_doc_max_bytes`); past it, split across nested
  files.
- **Command-first.** Codex's guidance is to **lead with commands, not prose** —
  setup, then test, then deploy, then debug. It's instruction, not enforcement,
  though: `AGENTS.md` lowers the *probability* of mistakes; for the *possibility*
  of a dangerous action you still need sandbox/exec policies. Verify what the
  agent actually absorbed: `codex --ask-for-approval never "Summarize current
  instructions."`

### How the three fit together

They're layers, not competitors. The 2026 consensus:

| Layer | Mechanism | Answers | Loads |
| --- | --- | --- | --- |
| Ambient project context | `AGENTS.md` (+ `CLAUDE.md`) | *"How do we build, test, and code here?"* | Always |
| Invokable procedures | **Skills** / Cursor rules | *"How do we do this specific task?"* | On demand |
| Live actions & data | MCP servers | *"What can the agent actually call?"* | On call |

The convergent lessons — the things all three docs independently insist on —
are worth pinning down, because they're the durable part:

1. **Metadata/description is the router.** Whatever the tool calls it, one short
   string decides whether the guidance is even seen. Spend disproportionate care
   there.
2. **Load on demand, not always.** Keep the always-on layer (`AGENTS.md`,
   "Always" rules) small; push procedures behind a trigger.
3. **Reference, don't inline.** Link to files; don't paste them. ~500 lines is
   the shared ceiling for a single always-relevant file.
4. **Don't teach the model what it knows.** Add only project- or task-specific
   context. Delete general explanations.
5. **Version-control it, test it on real tasks, iterate.** These files are code;
   treat them like code.

## Surface differences that bite

The same `SKILL.md` runs in environments with different powers. Plan for the
lowest common denominator you target:

| Surface | Network | Runtime package install | Sharing |
| --- | --- | --- | --- |
| **Claude Code** | Full (as any local program) | Discouraged (install locally, not globally) | Personal `~/.claude/skills/`, project `.claude/skills/`, or a plugin |
| **claude.ai** | Varies by user/admin setting | From npm/PyPI/GitHub, when enabled | Per-user upload (zip); not org-wide |
| **Claude API** | **None** | **None** — pre-installed packages only | Workspace-wide upload via the Skills API |

If a script needs a network call or a `pip install` at runtime, it will work in
Claude Code, maybe on claude.ai, and **not at all** on the API. Say which
packages you need in the body, and don't assume they're present.

### Claude Code extensions

Beyond the two required fields, Claude Code recognizes optional frontmatter that
does not exist in the base spec (use these only for Claude-Code-targeted skills;
they'll trip validation on the API):

| Field | Use |
| --- | --- |
| `disable-model-invocation: true` | Only *you* can invoke it (`/name`); the model won't fire it automatically. For side-effecting workflows — `/commit`, `/deploy` — where you control the timing. |
| `user-invocable: false` | Only the *model* can invoke it; hidden from the `/` menu. For background knowledge that isn't a user action (e.g. `legacy-system-context`). |
| `allowed-tools` | Tools the model may use without a permission prompt during the invoking turn (e.g. `Read Grep`). |
| `when_to_use` | Extra trigger context appended to `description` in the listing (counts toward a 1,536-char cap). |
| `context: fork` | Run the skill in a forked subagent context. |

## Security: skills are executable trust

A skill can direct the agent to run code and call tools, so **install skills only
from sources you trust** — ones you wrote or got from a known-good publisher.
Before using a third-party skill, **audit every file in it** — `SKILL.md`,
scripts, and resources — for anything that doesn't match its stated purpose:
unexpected network calls, odd file access, data being sent out. Skills that fetch
from external URLs are especially risky, since fetched content can carry
injected instructions, and even a trustworthy skill can go bad if its remote
dependency changes. Treat adding a skill like installing software with the
agent's privileges.

---

## Sources

**Anthropic — Agent Skills**
- [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- [Extend Claude with skills (Claude Code docs)](https://code.claude.com/docs/en/skills)
- [Equipping agents for the real world with Agent Skills (engineering blog)](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [anthropics/skills repository](https://github.com/anthropics/skills)

**Cursor — rules**
- [Cursor docs: Rules](https://cursor.com/docs/context/rules)

**OpenAI Codex / cross-tool standard — `AGENTS.md`**
- [agents.md — the open format](https://agents.md/)
- [Custom instructions with AGENTS.md (OpenAI/ChatGPT Codex docs)](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
