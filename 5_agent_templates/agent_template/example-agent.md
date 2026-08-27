---
# name: identifier. lowercase letters, numbers, hyphens only. This is also the
#       filename you save it as (security-auditor -> security-auditor.md) and,
#       in Claude Code and Cursor, what the model @-mentions or auto-delegates
#       to. Keep it a noun phrase, not a sentence.
name: doing-the-thing
# description: THIRD PERSON. The router. Say what the agent specializes in AND
#              when to hand work to it, with concrete trigger phrases -- this is
#              the only field every harness reads before the agent is active.
#              See the walkthrough's comparison table for how each one surfaces
#              it (delegation hint, mode-picker blurb, whenToUse, ...).
description: <What this agent specializes in>. Use when <situation>, when the user asks to <task>, or mentions <trigger terms>.
# model: harness-specific id/alias, or "inherit" to use the parent's model.
#        Claude Code and Cursor both read this field as-is. OpenCode wants the
#        provider/model-id form (e.g. anthropic/claude-sonnet-4-6). Roo Code has
#        no model field in .roomodes at all -- see the walkthrough.
model: inherit
# tools: comma-separated allowlist. Omit to inherit everything the parent has.
#        Claude Code and Cursor read this the same way. OpenCode and Roo Code
#        use coarser read/edit/command/mcp categories instead -- the porting
#        script maps this list onto those categories for you. Include
#        Write/Edit if the agent's job is to actually produce a file, not
#        just draft text for something else to apply.
tools: Read, Grep, Glob, Bash, Write, Edit
# --- Optional, Claude-Code-specific fields. Harmless elsewhere (unrecognized
#     frontmatter keys are ignored by the other harnesses), but delete them if
#     you want the file to look intentional rather than accidental everywhere. ---
# disallowedTools: Write, Edit
# color: blue
---

<One or two sentences: the agent's role and area of expertise, written in
second person ("You are a ..."). This is the system prompt for whichever
session gets delegated to this agent -- assume it is already a capable model,
and only add what a specialist in this role needs to know that a generalist
wouldn't.>

## When you're invoked

<What situation brought you in, and what "done" looks like -- the thing the
parent conversation is actually waiting on.>

## How you work

<!-- Match freedom to fragility: prose steps for judgment calls with many valid
     routes, an exact numbered sequence with "do not deviate" for anything
     fragile or high-stakes. -->

1. <Step one>
2. <Step two>
3. <Step three>

## What you report back

<The shape of the final answer the parent conversation should get -- this
matters more for an agent than a skill, since a subagent's reasoning is
usually discarded and only its final message returns.>
