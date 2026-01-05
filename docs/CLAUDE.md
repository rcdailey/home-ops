# Documentation Instructions for Claude

## Absolute Required Directives

Most of these rules repeat general markdown lint rules.

- Validate ALL `*.md` changes with `markdownlint-cli2` CLI application to check for lint violations
  and formatting issues.
- You MUST separate links from the vanity text. Instead of `[text](url)` you MUST do
  `[text][anchor]` or `[text-and-anchor]` with a separate link at the bottom of the containing
  section e.g. `[anchor]: http://foo.com`.
- You MUST NOT use bold text as a replacement for headings. Instead of `**This Looks Like A
  Section**`, do `## This is an actual section`.
- Text MUST be hard-wrapped at column 100
- All fenced code blocks MUST have a language specified after it (e.g. `txt` after the 3 opening
  tickmarks)
- Bullet point lists, headings, sections, and other non-contiguous or intentionally separate forms
  of text MUST be separated by a single blank line.

## Docs Structure

Below is an explanation of documentation subdirectories and their purpose.

- `architecture`: Long-term documentation about system design, architectural decisions, and the
  rationale behind technology choices.
- `decisions`: Architecture Decision Records (ADRs) documenting significant technical decisions with
  context, alternatives considered, and rationale. Use format `NNN-short-title.md` with sequential
  numbering. **MANDATORY: Read `decisions/TEMPLATE.md` before creating or editing any ADR.** The
  template structure must be followed exactly.
- `memory-bank`: Ephemeral documentation for temporary context and working memory. Used for ongoing
  constraints, temporary workarounds, or work spanning multiple sessions. Content is expected to
  become stale and should be removed once no longer relevant.
- `runbooks`: Step-by-step operational procedures for routine maintenance, recovery, or remediation
  tasks. Focused on "how to perform X" rather than "why X happened."
- `troubleshooting`: Historical investigations of complex issues with root cause analysis and
  resolution details. Documents past problems for reference, not necessarily reusable procedures.
