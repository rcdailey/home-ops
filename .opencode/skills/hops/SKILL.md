---
name: hops
description: >-
  Use when adding, modifying, debugging, refactoring, or reviewing `hops` CLI commands and domain
  modules in `scripts/hops/` and `scripts/hops.sh`; creating new subcommands, click groups, or
  output formatters; changing core helpers (`core/runner.py`, `core/format.py`, `core/nodes.py`,
  `core/workload.py`, `core/time.py`, `core/resolve.py`, `core/helm.py`); extending cluster
  introspection coverage (node, storage, app, flux, query, debug, dns, backup, validate). Triggers
  on phrases like "add a hops command", "fix hops output", "new hops domain", "extend hops", the
  `hops` escape hatch in AGENTS.md, or any edit to files under `scripts/hops/`. Do NOT use for
  simply running existing `hops` commands during diagnosis (no skill needed) or for
  non-cluster/app-specific scripts (e.g., `hass.sh`).
---

# hops CLI Development

`hops` is an LLM-optimized cluster operations CLI at `scripts/hops/`. It wraps kubectl, talosctl,
flux, ceph, and other cluster tools into domain-oriented commands that produce compact, pre-filtered
output designed for LLM context windows.

## Inclusion Litmus Test

A command belongs in `hops` only if it relates to **cluster infrastructure**: kubectl, talosctl,
helm, flux, ceph, Prometheus/VictoriaMetrics, VictoriaLogs, Blocky DNS, or similar infrastructure
tooling.

Commands that fail the test (stay standalone):

- App-specific utilities that happen to use kubectl exec (Home Assistant API, Recyclarr config)
- Pure utility scripts (icon search, YAML annotation, git hooks)
- Dev tooling (Vector testing, pre-commit hooks)

Ceph passes (storage infrastructure). Blocky DNS passes (cluster DNS infrastructure). hass fails
(application-level automation).

## Architecture

Run `./scripts/hops.sh <domain> --help` for command details. Do not maintain a parallel command list
in documentation; the CLI is authoritative.

Domains may be flat modules or packages. Both expose a Click `cli`; package domains register their
commands through `__init__.py`. Root auto-discovery requires no central command registry.

- Keep files below 400 lines. Split a module before unrelated workflows accumulate in it.
- Put shared logic in `core/`; domain modules do not import from one another.
- Reuse helpers from `core.format`, `core.runner`, `core.time`, `core.nodes`, `core.workload`,
  `core.resolve`, and `core.helm` instead of creating local equivalents.
- Use `core.runner.tools_curl` for in-cluster HTTP.
- Fetch each Kubernetes resource once per command and pass the result to helpers.
- Escape every user-provided DNS query value with `dns.psql.sql_escape`.
- Keep Click wiring in command modules; move substantial implementations into sibling modules.
- Do not add aliases that only delegate to another command.

## Design Principles

### Workflow, Not Passthrough

`hops` commands MUST embody an investigative workflow; they MUST NOT be thin reformatters around a
single upstream command. The entire reason `hops` exists is that raw CLIs force multi-step
drill-downs that waste LLM context. A command that just prettifies one `kubectl get` call has no
reason to live here; use kubectl directly.

A command earns its place when it does at least one of:

- Correlates multiple data sources in a single call (e.g., pod state + containers + events +
  previous logs for crash diagnosis)
- Applies heuristics so the caller does not have to drill down (e.g., auto-fetch `--previous` logs
  when `restartCount > 0`; pick most recent Succeeded pod when no Running pod exists)
- Resolves inputs flexibly across failure modes (e.g., workload name, app label, pod name prefix,
  orphan pods whose parent workload was deleted)
- Hides transient/edge-case noise that the caller does not need to handle (e.g., terminated pods,
  missing parent controllers, empty event lists) unless the situation is genuinely blocking

Design check when adding or editing a command: what sequence of kubectl/talosctl/flux/helm
invocations would an investigator run to answer this question end-to-end? Fold that sequence into
the single `hops` command, in the order the investigator needs it. If the answer is "one kubectl
invocation," either the command adds no value or the workflow has not been fully identified yet.

Anti-patterns to reject in code review:

- A command whose body is effectively `kubectl get X -o json | reformat`
- Returning early on edge cases the caller could handle transparently (terminated pods, deleted
  workloads, missing optional fields)
- Requiring a follow-up command to fetch context that every caller of the primary command needs
- Resolver that exits with `not found` when a less strict match (pod name, label selector, fuzzy
  suffix) would have succeeded

Reference implementation: `hops app pod` (implemented in `app/pod_detail.py`). One call resolves the
target (workload or orphan pod), emits pod summary, container state machine, previous-termination
table, auto-fetched `--previous` logs for each restarted container, and pod-scoped events. That is
the bar.

### Read-Only by Design

`hops` never mutates cluster state. No `kubectl apply`, no `helm upgrade`. Two controlled exceptions
exist:

- Ephemeral debug pods (`hops debug`): creates a pod, captures output, deletes in `try/finally`
- Flux suspend/resume (`hops flux suspend/resume`): reversible state toggle for maintenance (storage
  migrations, immutable field changes). Finds Kustomization + HelmRelease namespaces automatically
  and handles both in one call.

### Output Standards

All output is plain text optimized for LLM token efficiency:

- Fixed-width tables with space-aligned columns, no borders, no decorators
- Short header abbreviations (cp not control-plane)
- Key-value format for single-resource summaries
- One line per entity in tables
- Omit healthy/normal items when showing problems
- No ANSI color codes, no unicode symbols, no emoji
- Truncate long messages (120 chars default)

### Click Conventions

- All Groups default to `no_args_is_help=True` (shows help without subcommand)
- Use `@click.group()` for domain modules, `@cli.command()` for leaf commands
- Common patterns: `-n/--namespace`, `--json` for raw output, `--limit`
- Time options via the `time_options()` decorator factory in `core.time`

### Dependencies

- Only external dependency: `click` (in pyproject.toml; auto-installed by uv)
- Shell out to cluster tools; parse their `-o json` output in Python
- `core.runner` handles subprocess execution, JSON/JSONL parsing, error handling, `tools_curl`
  (in-cluster HTTP via rook-ceph-tools pod)
- `core.nodes` caches node name/IP mapping per process
- `core.workload` provides cascading workload resolution
- `core.resolve` provides the unified resolver registry

### Error Handling

- One-line error messages to stderr, then `sys.exit(1)`
- No stack traces in normal operation
- Failed subprocess: show first line of stderr
- Missing tool: "error: `<tool>` not found in PATH"

## Adding a New Command

1. Identify the investigative workflow: enumerate the sequence of raw CLI calls a human or LLM would
   run to fully answer the question. If the list has one item, reconsider whether the command
   belongs in `hops`.
2. Decide which domain module the command belongs to (or create a new one).
3. Check the core layer (see Module Structure) for existing utilities before writing new ones.
    Common needs: `core.workload.resolve_app` for app resolution, `core.runner.tools_curl` for
    in-cluster HTTP, `core.format.age_str` for timestamp display, `core.time.TimeRange` for time
    range options, `core.resolve.resolve` for unified target resolution.
4. Add a click command function with appropriate arguments and options.
5. Use `core.runner.run_json()` or `core.runner.kubectl_json()` for data fetching.
6. Fold the full workflow (correlation, heuristics, flexible resolution, auto-fetch of downstream
    context) into the single command; see "Workflow, Not Passthrough" above.
7. If the implementation exceeds ~30 lines, extract it to a sibling module. If a flat domain module
    would exceed 400 lines, convert to a package directory.
8. Use `core.format.table()` or `core.format.kv()` for output.
9. Test against live cluster: `./scripts/hops.sh <domain> <command> <args>`
10. Measure token count: `./scripts/hops.sh <command> 2>&1 | ttok`

## Verification

No test suite exists; validate adhoc against the live cluster (see `python-scripting` skill,
Adhoc Verification). Every change MUST be exercised before reporting done:

```bash
# Run the changed command, plus a failure path (nonexistent target)
./scripts/hops.sh <domain> <command> <args>
./scripts/hops.sh <domain> <command> nonexistent-app

# Pure functions: exercise inline, print observed beside expected
uv run --project scripts/hops python - <<'EOF'
from hops.core.format import age_str
print("age:", age_str("2026-07-25T12:00:00Z"), "| expect a short relative string")
EOF

# Compare token usage vs raw equivalent
./scripts/hops.sh node list 2>&1 | ttok
kubectl get nodes -o wide 2>&1 | ttok
```
