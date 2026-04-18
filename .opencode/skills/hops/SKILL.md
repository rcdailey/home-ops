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
  app.py                 hops app (list, pods, events, logs, resources, secrets, diagnose, ls, cat, du)
  flux.py                hops flux (status, hr, ks, test, values, defaults)
  debug.py               hops debug (dns, curl; ephemeral pods)
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

1. Decide which domain module the command belongs to (or create a new one)
2. Add a click command function with appropriate arguments and options
3. Use `_runner.run_json()` or `_runner.kubectl_json()` for data fetching
4. Use `_format.table()` or `_format.kv()` for output
5. Test against live cluster: `./scripts/hops.py <domain> <command> <args>`
6. Measure token count: `./scripts/hops.py <command> 2>&1 | ttok`

## Testing Changes

```bash
# Verify the command works
./scripts/hops.py <domain> <command>

# Compare token usage vs raw equivalent
./scripts/hops.py node list 2>&1 | ttok
kubectl get nodes -o wide 2>&1 | ttok
```
