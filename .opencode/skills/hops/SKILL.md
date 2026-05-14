---
name: hops
description: >-
  Use when adding, modifying, debugging, refactoring, or reviewing `hops` CLI commands and domain
  modules in `scripts/hops/` and `scripts/hops.py`; creating new subcommands, click groups, or
  output formatters; changing subprocess helpers (`_runner.py`, `_format.py`, `_nodes.py`,
  `_workload.py`, `_time.py`, `_gateway.py`, `_pod_detail.py`); extending cluster introspection
  coverage (node, storage, app, flux, query, debug, dns, backup, validate). Triggers on phrases
  like "add a hops command", "fix hops output", "new hops domain", "extend hops", the `hops`
  escape hatch in AGENTS.md, or any edit to files under `scripts/hops/`. Do NOT use for simply
  running existing `hops` commands during diagnosis (no skill needed) or for non-cluster/app-specific
  scripts (e.g., `hass.py`).
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
  _runner.py             Subprocess runner (JSON, JSONL, kubectl, tools_curl)
  _format.py             Tables, key-value, truncation, age_str, format_timestamp
  _time.py               TimeRange dataclass, time_options decorator (shared by query modules)
  _nodes.py              Node name/IP resolution (cached per session)
  _workload.py           Workload resolution (exact > label > suffix > prefix > substring),
                         resolve_pods, pick_pod_for_logs, find_running_pod
  _diagnose.py           Diagnose internals (workload, gateway, events, flux status)
  _pod_detail.py         Pod detail diagnostic (container state, previous/failure logs, events)
  _gateway.py            Gateway introspection (HTTPRoute, policies, EnvoyProxy tracing)
  _helm.py               Helm chart resolution and YAML value helpers
  node.py                hops node (list, disks, status)
  storage.py             hops storage (ceph status/osd/io, pvcs with PV driver correlation)
  app.py                 hops app (list, unhealthy, pods, pod, events, logs, resources, secrets, diagnose, ls, cat, du)
  flux.py                hops flux (status, hr, ks, values, defaults, suspend, resume)
  debug.py               hops debug (dns, curl, route; ephemeral pods + gateway diagnostics)
  query/                 hops query (PromQL + container stats at top level; alerts + logs subgroups)
    __init__.py          Flattens metrics + alerts commands into query group
    _vm.py               VictoriaMetrics API helpers (query_vm, query_vmalert, is_ignored_alert)
    _client.py           VictoriaLogs HTTP client (VictoriaLogsClient)
    metrics.py           PromQL queries, container stats (cpu, memory, query, labels, metrics)
    alerts.py            Alert commands (alerts, alert, rules)
    logs.py              VictoriaLogs (LogSQL, stats, hits, fields)
  db.py                  hops db (status; CNPG cluster overview with pods, PDBs, PVCs, backups)
  dns.py                 hops dns (search, logs, blocked, test; port of blocky.py)
  backup.py              hops backup (status: Volsync + CNPG backup health; kopia wrapper)
  validate.py            hops validate (vmrules)
```

## Auto-Discovery

`cli.py` scans the package for modules exposing a `cli` attribute (a click Group or Command).
Modules starting with `_` are skipped. Adding a new domain means creating a new `.py` file with a
`cli` click group; no registration needed.

## Module Structure

### File Size

Domain modules (click command files) MUST stay under 500 lines. When a module approaches the limit,
extract implementation logic into `_` prefixed helper modules; keep click decorators and thin
delegation in the domain module.

Splitting signals: a file has grown past 500 lines, or a single function exceeds 80 lines, or two
functions in the same file share no imports or data flow.

### Helper Hierarchy

Shared logic lives in the helper module closest to its concern. Before writing a new utility
function, check whether one already exists in the appropriate layer:

| Concern | Module | Examples |
| --- | --- | --- |
| Formatting, display | `_format.py` | `table`, `kv`, `age_str`, `format_timestamp`, `human_bytes`, `truncate` |
| Subprocess, HTTP | `_runner.py` | `run`, `run_json`, `kubectl_json`, `tools_curl`, `ceph_json` |
| Time ranges | `_time.py` | `TimeRange`, `time_options` |
| Workload resolution | `_workload.py` | `resolve_app`, `resolve_pods`, `find_running_pod`, `pick_pod_for_logs` |
| Node resolution | `_nodes.py` | `get_all`, `resolve_ip`, `resolve_name` |
| Gateway introspection | `_gateway.py` | `find_httproute`, `fetch_gateway`, `fetch_envoy_proxy` |
| Helm chart resolution | `_helm.py` | `resolve_hr`, `helm_chart_args` |
| VM API | `query/_vm.py` | `query_vm`, `query_vmalert`, `is_ignored_alert` |
| VL API | `query/_client.py` | `VictoriaLogsClient` |

MUST NOT duplicate logic that already exists in a helper. Common violations to watch for:

- Timestamp-to-age conversion: use `_format.age_str`, not a local `_age_str`
- Bytes-to-human formatting: use `_format.human_bytes`, not a local `format_memory`
- In-cluster HTTP: use `_runner.tools_curl`, not hand-rolled `kubectl exec ... curl` commands
- Workload-to-pod resolution: use `_workload.resolve_pods`, not local pod-fetching logic

### In-Cluster HTTP

All HTTP requests to in-cluster services (VictoriaMetrics, VictoriaLogs, future services) MUST use
`_runner.tools_curl`. This function executes curl via the rook-ceph-tools pod with standardized
connection timeout, error classification (unreachable vs. failed), and one-line error output.
Callers parse the returned string into JSON or use it raw.

Do not construct kubectl exec curl commands directly in domain modules.

### Domain Module Boundaries

- One click group per domain module. Do not split a group's commands across files.
- Click decorators and argument wiring stay in the domain module.
- Implementation bodies exceeding ~30 lines SHOULD move to a `_` helper, with the click function
  delegating in one call (see `app.pod_detail` delegating to `_pod_detail.diagnose_pod`).
- When multiple click commands share the same resolve-then-exec pattern, extract a shared helper
  (see `app._exec_in_pod` for ls/cat/du).
- Commands that share 80%+ of their body MUST extract a shared implementation parameterized by the
  difference (see `dns._query_dns_logs` for logs/blocked).

### Data Fetching Discipline

- MUST NOT fetch the same Kubernetes resource twice in one command. Store the result and reuse it.
- When a command correlates multiple resources (e.g., HTTPRoute + Gateway + policies), fetch each
  once and pass the data dict to helper functions rather than re-fetching inside helpers.
- Tab-delimited or structured CLI output (psql, talosctl) SHOULD use a generic parser parameterized
  by field names, not per-query parser functions.

### SQL Safety

The `dns.py` module constructs SQL from user input for psql queries. All user-provided values
(client names, domain patterns, timestamps) MUST be escaped via `_sql_escape` before interpolation
into SQL strings.

### Alias and Redirect Commands

Do not create commands that just delegate to another command without adding value. If `hops storage
disks` would do exactly what `hops node disks` does, the command should not exist. Every command
MUST add correlation, heuristics, or context beyond what the target already provides.

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

Reference implementation: `hops app pod` (implemented in `_pod_detail.py`). One call resolves the
target (workload or orphan pod), emits pod summary, container state machine, previous-termination
table, auto-fetched `--previous` logs for each restarted container, and pod-scoped events. That is
the bar.

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
- Time options via the `time_options()` decorator factory in `_time.py`

### Dependencies

- Only external dependency: `click` (in pyproject.toml; auto-installed by uv)
- Shell out to cluster tools; parse their `-o json` output in Python
- `_runner.py` handles subprocess execution, JSON/JSONL parsing, error handling, `tools_curl`
  (in-cluster HTTP via rook-ceph-tools pod)
- `_nodes.py` caches node name/IP mapping per process
- `_workload.py` provides cascading workload resolution plus `resolve_pods`, `pick_pod_for_logs`,
  `find_running_pod`

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
3. Check the helper hierarchy (see Module Structure) for existing utilities before writing new ones.
   Common needs: `_workload.resolve_app` for app resolution, `_runner.tools_curl` for in-cluster
   HTTP, `_format.age_str` for timestamp display, `_time.TimeRange` for time range options.
4. Add a click command function with appropriate arguments and options.
5. Use `_runner.run_json()` or `_runner.kubectl_json()` for data fetching.
6. Fold the full workflow (correlation, heuristics, flexible resolution, auto-fetch of downstream
   context) into the single command; see "Workflow, Not Passthrough" above.
7. If the implementation exceeds ~30 lines, extract it to a `_` helper module. If the domain module
   would exceed 500 lines, extract before adding.
8. Use `_format.table()` or `_format.kv()` for output.
9. Test against live cluster: `./scripts/hops.py <domain> <command> <args>`
10. Measure token count: `./scripts/hops.py <command> 2>&1 | ttok`

## Testing Changes

```bash
# Verify the command works
./scripts/hops.py <domain> <command>

# Compare token usage vs raw equivalent
./scripts/hops.py node list 2>&1 | ttok
kubectl get nodes -o wide 2>&1 | ttok
```
