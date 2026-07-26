# Scripts Directives

## Lint and type-check suppression

Suppression is prohibited. This covers `# noqa`, `# ruff: ignore`, `# ruff: disable`, `# type:
ignore`, `# pyright: ignore`, `# nosec`, `# pylint: disable`, `# shellcheck disable`, and
per-rule `select`/`ignore`/`extend-select` entries in `ruff.toml`.

A finding names a real defect or a design smell. MUST fix the cause: narrow the exception to what
the block can actually raise, give the function the return type it really has, restructure a
registration import so the name is used. Silencing the check leaves the defect in place and hides it
from the next reader.

MUST NOT add a suppression to make a check pass, including when the check was passing before a
linter upgrade widened its rule set. When no fix preserves behavior, MUST stop and surface the
finding to the user: rule code, location, why the flagged construct is correct as written, and what
a real fix would cost. Subagents report `blocked` instead. Approval is per-occurrence, and an
approved suppression MUST carry the approved rationale as its comment text.

## Verification

These projects carry no test suites. See the repo-root `hops` verification rule, which applies to
every script project here: exercise the affected commands directly, on both success and failure
paths, before reporting done.
