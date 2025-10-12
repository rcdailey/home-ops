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
