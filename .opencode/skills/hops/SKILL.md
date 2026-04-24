---
name: hops
description: >-
  Use when adding, modifying, debugging, refactoring, or reviewing `hops` CLI commands and domain
  modules in `scripts/hops/` and `scripts/hops.py`; creating new subcommands, click groups, or
  output formatters; changing subprocess helpers (`_runner.py`, `_format.py`, `_nodes.py`,
  `_workload.py`); extending cluster introspection coverage (node, storage, app, flux, query,
  debug, dns, backup, validate). Triggers on phrases like "add a hops command", "fix hops
  output", "new hops domain", "extend hops", the `hops` escape hatch in AGENTS.md, or any edit to
  files under `scripts/hops/`. Do NOT use for simply running existing `hops` commands during
  diagnosis (no skill needed) or for non-cluster/app-specific scripts (e.g., `hass.py`).
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

```txt
scripts/hops.py          Entry point (uv shebang, auto-installs deps)
scripts/hops/
  pyproject.toml         click dependency
  __init__.py
  __main__.py            python -m hops support
  cli.py                 Root group with auto-discovery
  _runner.py             Subprocess runner (JSON, JSONL, kubectl helpers)
  _format.py             Tables, key-value, truncation (no color, no unicode)
  _nodes.py              Node name/IP resolution (cached per session)
  _workload.py           Workload resolution (exact name > app label > suffix match)
  node.py                hops node (list, disks, status)
  storage.py             hops storage (ceph status/osd/io, pvcs, disks)
  app.py                 hops app (list, pods, pod, events, logs, resources, secrets, diagnose, ls, cat, du)
  flux.py                hops flux (status, hr, ks, test, values, defaults)
  debug.py               hops debug (dns, curl, route; ephemeral pods + gateway diagnostics)
  query/                 hops query (metrics, logs)
    __init__.py
    metrics.py           VictoriaMetrics (port of query-vm.py)
    logs.py              VictoriaLogs (port of query-victorialogs.py)
  dns.py                 hops dns (search, logs, blocked, test; port of blocky.py)
  backup.py              hops backup (kopia wrapper)
  validate.py            hops validate (vmrules)
```

## Auto-Discovery

`cli.py` scans the package for modules exposing a `cli` attribute (a click Group or Command).
Modules starting with `_` are skipped. Adding a new domain means creating a new `.py` file with a
`cli` click group; no registration needed.

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

Reference implementation: `hops app pod` in `app.py`. One call resolves the target (workload or
orphan pod), emits pod summary, container state machine, previous-termination table, auto-fetched
`--previous` logs for each restarted container, and pod-scoped events. That is the bar.

### Stewardship / Audit Obligation

Loading this skill carries an obligation beyond the immediate task: passthrough drift in
`scripts/hops/` MUST be audited and fixed even when unrelated to the reason the skill was loaded.
The no-passthrough rule is a stewardship discipline, not a code-review checkbox; without active
maintenance it decays into an aspirational comment while the codebase fills with thin wrappers.

When this skill is loaded for any reason, MUST run this audit pass in the current session:

1. MUST scan the domain module being edited plus one adjacent module in `scripts/hops/` for the
   signals in the AGENTS.md `hops` stewardship obligation (thin wrappers, missing correlation,
   strict resolvers rejecting reasonable edge cases, repeated call patterns that should be one
   command).
2. MUST fix bounded drift inline (single function, single module, clear intent).
3. Drift requiring broader refactor MUST be surfaced explicitly in the session response so the user
   can prioritize. MUST NOT silently widen scope. MUST NOT defer with a "TODO for later" that will
   never be noticed.
4. MUST cap audit-driven refactors at two per session. The goal is steady erosion of drift, not a
   single-session rewrite that destabilizes the tool.

A passthrough caught during an unrelated session is more valuable than a perfect refactor delayed
until someone happens to notice. Err toward acting.

The following rationalizations for skipping the audit MUST be rejected:

- "The user did not ask for it." The AGENTS.md directive does; that is the mandate.
- "It is out of scope for this change." Stewardship is cross-cutting by design.
- "It is only a small passthrough; it is fine." Small passthroughs are how the rule dies.
- "I will open a follow-up." Follow-ups without user action die in the backlog.

### Read-Only by Design

`hops` never mutates cluster state. No `flux reconcile`, no `kubectl apply`, no `helm upgrade`. The
sole exception is ephemeral debug pods (`hops debug`), which create a pod, capture output, and
delete the pod in a `try/finally` block.

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
- Time options via the `time_options()` decorator factory in `query/metrics.py`

### Dependencies

- Only external dependency: `click` (in pyproject.toml; auto-installed by uv)
- Shell out to cluster tools; parse their `-o json` output in Python
- `_runner.py` handles subprocess execution, JSON/JSONL parsing, error handling
- `_nodes.py` caches node name/IP mapping per process

### Error Handling

- One-line error messages to stderr, then `sys.exit(1)`
- No stack traces in normal operation
- Failed subprocess: show first line of stderr
- Missing tool: "error: `<tool>` not found in PATH"

## Adding a New Command

1. Identify the investigative workflow: enumerate the sequence of raw CLI calls a human or LLM would
   run to fully answer the question. If the list has one item, reconsider whether the command
   belongs in `hops`.
2. Decide which domain module the command belongs to (or create a new one)
3. Add a click command function with appropriate arguments and options
4. Use `_runner.run_json()` or `_runner.kubectl_json()` for data fetching
5. Fold the full workflow (correlation, heuristics, flexible resolution, auto-fetch of downstream
   context) into the single command; see "Workflow, Not Passthrough" above
6. Use `_format.table()` or `_format.kv()` for output
7. Test against live cluster: `./scripts/hops.py <domain> <command> <args>`
8. Measure token count: `./scripts/hops.py <command> 2>&1 | ttok`

## Testing Changes

```bash
# Verify the command works
./scripts/hops.py <domain> <command>

# Compare token usage vs raw equivalent
./scripts/hops.py node list 2>&1 | ttok
kubectl get nodes -o wide 2>&1 | ttok
```
