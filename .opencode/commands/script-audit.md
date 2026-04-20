---
description: Retrofit a living script (hops, hass) against real session friction
---

Audit the target script against friction observed in the current session and mercilessly fix gaps,
bugs, and awkward ergonomics so the next LLM does not hit the same walls.

Arguments: $ARGUMENTS

## Target Resolution

Resolve the target script from the argument or session context:

- `hops` or `./scripts/hops.py` -> target is `scripts/hops/` (load the `hops` skill)
- `hass` or `./scripts/hass.py` -> target is `scripts/hass/` (load the `home-assistant` skill)
- No argument -> infer from session: whichever script the session exercised most heavily. If both
  were used, ask which to audit. If neither, stop and report that there is nothing to audit.

MUST load the matching skill alone (no parallel tool calls) before reading source or editing.

## Evidence: Session Friction Only

The sole evidence source is the current session. Do NOT scan git log, do NOT rg the source for
TODOs, do NOT open a broad refactor safari. Walk backward through this session and extract concrete
moments where the script failed the LLM:

- Reached past the script to a raw CLI (kubectl, talosctl, flux, helm, curl, jq on raw endpoints)
  because the script lacked the capability or produced the wrong shape
- Ran two or more script invocations in sequence to answer one question
- Parsed the script's output manually to pull a field that should have been surfaced directly
- Hit a resolver that rejected a reasonable input (orphan pod, terminated workload, fuzzy name,
  missing entity)
- Got output so verbose the response truncated or context pressure spiked
- Got output so terse a follow-up call was required for trivial context
- Worked around a bug, edge case, or missing flag with shell glue

For each friction point, record: what the LLM needed, what the script delivered, the workaround
used, and which module/command owns the gap.

If the session yielded zero friction points, stop and say so. Do not invent gaps.

## Audit Principles

Apply the design philosophy from the loaded skill. Both scripts share these non-negotiables:

- **Workflow, not passthrough.** A command must correlate sources, apply heuristics, or resolve
  inputs flexibly. A reformatter around one upstream call does not belong.
- **Token-optimized output by default.** Prose over JSON, fewer lines over more, key-value and
  fixed-width tables over bordered tables, omit healthy/normal rows when showing problems. Verbose
  modes are opt-in flags (`--json`, `--all`, `-v`), never the default.
- **Flexible input resolution.** Accept names, labels, prefixes, and orphan/edge-case inputs where a
  reasonable caller would expect a match.
- **Merciless refactor.** Backward compatibility is NOT a constraint. Rename flags, remove
  subcommands, restructure modules, change output shapes. No dual-support shims, no deprecation
  warnings. If an old pattern is wrong, delete it and update the skill doc in the same pass.
- **Fold follow-ups into the primary command.** If every caller of command X needs to also run Y,
  Y's output belongs inside X.

## Process

### 1. Extract Friction

Produce an inline list of friction points from the session (title, need, gap, workaround, owning
module). Keep it compact; this is working memory, not a deliverable.

### 2. Classify Fixes

For each friction point, pick one:

- **Fix in place** -- bounded change to an existing command (new flag, better resolver, richer
  output, bug fix)
- **Fold together** -- merge multiple commands or auto-fetch downstream context
- **New command** -- the workflow is genuinely missing and earns its place per the skill's inclusion
  test
- **Out of scope** -- belongs to a different tool or is a one-off; note and drop

### 3. Apply

Implement every non-dropped fix in this session. Remove superseded code outright. Update the
relevant skill doc (`SKILL.md`) in the same pass when behavior or interfaces change. Update
`AGENTS.md` only if a directive referenced the changed surface.

### 4. Verify

Run each changed command against the live target at least once:

- `hops`: `./scripts/hops.py <domain> <command> <args>` plus the exact invocation that exposed the
  friction
- `hass`: `./scripts/hass.py <subcommand> <args>` plus the failing invocation

Confirm output shape, token footprint (eyeball line count), and that the original workaround is no
longer needed. If a command produces large output, sanity-check with `ttok` or line count.

### 5. Report

Concise session response with this shape:

```txt
Target: <hops|hass>
Friction points: <N>
Fixes applied:
- <command>: <one-line summary>
- ...
Removed: <flags/commands/modules deleted>
Skill/docs updated: <paths>
Deferred: <items classified out of scope, with one-line reason>
```

Keep it under 20 lines. No diff dumps; the user reads those via git.

## Rules

- MUST load the matching skill (`hops` or `home-assistant`) alone before any edits
- MUST NOT commit or push; the user commits per the repo's GitOps rule
- MUST NOT preserve backward compatibility; remove old flags, commands, and output shapes outright
- MUST NOT add dual-support shims, deprecation warnings, or "legacy" branches
- MUST NOT introduce structured output (JSON, YAML) as a default; use prose/key-value/tables and
  gate structure behind an explicit flag
- MUST NOT scan git history, grep for TODOs, or expand scope beyond session-observed friction
- MUST delete obsolete skill/doc content in the same pass as the code change
- MUST cap the audit at friction points actually surfaced this session; inventing hypothetical gaps
  defeats the purpose
- If a fix is too large to land safely in-session, state that explicitly in the report with the
  smallest viable next step, do not leave half-applied changes
