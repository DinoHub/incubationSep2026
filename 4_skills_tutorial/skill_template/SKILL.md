---
# name: gerund preferred (writing-x, analyzing-y). lowercase/numbers/hyphens,
#       <=64 chars, no "anthropic"/"claude". In Claude Code the DIRECTORY name is
#       what you invoke; this field is the display label.
name: doing-the-thing
# description: the router. THIRD PERSON. Say WHAT it does AND WHEN to use it, with
#              concrete trigger terms/phrasings/file types. <=1024 chars, non-empty.
description: <What this skill does>. Use when <situation>, when the user mentions <terms>, or asks to <task>.
# --- Optional Claude Code extensions (delete if targeting claude.ai / the API) ---
# disable-model-invocation: true   # only you can run it via /name (side-effecting workflows)
# user-invocable: false            # only the model runs it (background knowledge, no /command)
# allowed-tools: Read Grep         # tools usable without a prompt during the invoking turn
---

# <Skill title>

<One or two sentences: what this is and the outcome it produces. Assume the model
is already smart — do NOT explain general concepts it already knows.>

## Get inputs / current state   <!-- optional: only if the skill needs live data -->

Run `bash scripts/example.sh` to gather <...>. If it reports <empty case>, tell
the user and stop rather than proceeding on bad input.
<!-- In Claude Code only, you can inline output instead: a line like  !`git status`  -->

## Instructions

<!-- Match freedom to fragility:
     - open task, many valid routes  -> prose steps (like below)
     - fragile/high-stakes sequence  -> "Run exactly this: ..."  + "do not modify" -->

1. <Step one>
2. <Step two>
3. <Step three>

## Workflow   <!-- optional: for multi-step tasks, give a checklist to copy -->

- [ ] Step 1: <do X>
- [ ] Step 2: <validate X>   <!-- validate -> fix -> repeat is the key loop -->
- [ ] Step 3: <only proceed once clean>

## Examples   <!-- strongly recommended when output STYLE matters -->

Input: <example input>
Output:
<example output showing the exact shape/tone you want>

## Details   <!-- optional: push long/rarely-needed material into references, ONE level deep -->

- Full conventions: see [references/reference.md](references/reference.md)
- <Another domain-specific reference, loaded only when needed>

<!-- Keep this file under ~500 lines. Past that, split into reference files. -->
