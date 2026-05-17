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

```txt
scripts/hops.sh          Shell wrapper (invokes uv run)
scripts/hops/
  hops/                  Package root (nested layout)
    cli.py               Root group with auto-discovery
  core/                  Shared helpers (domains import from here, never from each other)
    runner.py            Subprocess runner (JSON, JSONL, kubectl, tools_curl, ceph_json)
    format.py            Tables, key-value, truncation, age_str, human_bytes
    time.py              TimeRange dataclass, time_options decorator
    nodes.py             Node name/IP resolution (cached per session)
    workload.py          Workload resolution (cascading match strategies)
    resolve.py           Unified resolver registry (Workload, Gateway, Pod)
    helm.py              Helm chart resolution and YAML value helpers
  app/                   Package domain (auto-discovered via __init__.py cli attribute)
  flux/                  Package domain
  dns/                   Package domain
  query/                 Package domain (nested subgroups for logs)
  node.py, storage.py, debug.py, db.py, backup.py, validate.py  Flat domains
```

Domains are either flat files (`node.py`) or package directories (`app/`). Both expose a `cli` click
Group. Package domains split commands across submodules that register on the shared group.

## Auto-Discovery

`cli.py` scans the package for modules and packages exposing a `cli` attribute (a click Group or
Command). Modules starting with `_` are skipped. Adding a new domain means creating a `.py` file or
a package directory with a `cli` click group in its `__init__.py`; no registration needed. For
package-based domains (app/, flux/, dns/), the `__init__.py` defines the click group and imports
submodules that register commands on it.

## Module Structure

### File Size

All files MUST stay under 400 lines. When a module approaches the limit, split into a package
directory or extract logic into a sibling module.

Splitting signals: a file has grown past 300 lines, a single function exceeds 80 lines, or two
functions in the same file share no imports or data flow. Flat modules (single `.py` file) that
cross 400 lines MUST be converted to a package directory.

### Core Layer (`core/`)

Shared logic lives in `core/`. Domain modules import from `core.*`, never from each other. Before
writing a new utility function, check whether one already exists:

| Concern | Module | Examples |
| --- | --- | --- |
| Formatting, display | `core.format` | `table`, `kv`, `age_str`, `format_timestamp`, `human_bytes`, `truncate` |
| Subprocess, HTTP | `core.runner` | `run`, `run_json`, `kubectl_json`, `tools_curl`, `ceph_json` |
| Time ranges | `core.time` | `TimeRange`, `time_options` |
| Workload resolution | `core.workload` | `resolve_app`, `resolve_pods`, `find_running_pod`, `pick_pod_for_logs` |
| Unified resolution | `core.resolve` | `resolve`, `ResolvedTarget`, `TargetKind`, resolver registry |
| Node resolution | `core.nodes` | `get_all`, `resolve_ip`, `resolve_name` |
| Gateway introspection | `app.gateway` | `find_httproute`, `fetch_gateway`, `fetch_envoy_proxy` |
| Helm chart resolution | `core.helm` | `resolve_hr`, `helm_chart_args` |
| VM API | `query._vm` | `query_vm`, `query_vmalert`, `is_ignored_alert` |
| VL API | `query._client` | `VictoriaLogsClient` |

MUST NOT duplicate logic that already exists in a helper. Common violations to watch for:

- Timestamp-to-age conversion: use `core.format.age_str`, not a local `_age_str`
- Bytes-to-human formatting: use `core.format.human_bytes`, not a local `format_memory`
- In-cluster HTTP: use `core.runner.tools_curl`, not hand-rolled `kubectl exec ... curl` commands
- Workload-to-pod resolution: use `core.workload.resolve_pods`, not local pod-fetching logic
- Target resolution: use `core.resolve.resolve()` for the unified resolver, not ad-hoc fallback
  chains

### Unified Resolver (`core/resolve.py`)

The resolver eliminates ad-hoc fallback chains for target resolution. It tries three resolvers in
priority order (Workload, Gateway, Pod) and returns a `ResolvedTarget` dataclass with the matched
kind, name, namespace, optional workload, and pods.

To add a new resource category (e.g., a new operator-managed resource), create a class implementing
the `Resolver` protocol with a `try_resolve` method and append it to `_REGISTRY`.

The `--explain` flag on `app diagnose` prints the resolver trace, showing which resolvers were tried
and what matched.

### In-Cluster HTTP

All HTTP requests to in-cluster services (VictoriaMetrics, VictoriaLogs, future services) MUST use
`core.runner.tools_curl`. This function executes curl via the rook-ceph-tools pod with standardized
connection timeout, error classification (unreachable vs. failed), and one-line error output.
Callers parse the returned string into JSON or use it raw.

Do not construct kubectl exec curl commands directly in domain modules.

### Domain Module Boundaries

- One click group per domain package or module. Package domains (app/, flux/, dns/) split commands
  across submodules that all register on the shared `cli` group from `__init__.py`.
- Click decorators and argument wiring stay in command modules. Implementation bodies exceeding ~30
  lines SHOULD move to a sibling module (see `app.pod_detail` for pod diagnostics).
- When multiple click commands share the same resolve-then-exec pattern, extract a shared helper
  (see `app.commands._exec_in_pod` for ls/cat/du).
- Commands that share 80%+ of their body MUST extract a shared implementation parameterized by the
  difference (see `dns.render.query_dns_logs` for logs/blocked).

### Data Fetching Discipline

- MUST NOT fetch the same Kubernetes resource twice in one command. Store the result and reuse it.
- When a command correlates multiple resources (e.g., HTTPRoute + Gateway + policies), fetch each
  once and pass the data dict to helper functions rather than re-fetching inside helpers.
- Tab-delimited or structured CLI output (psql, talosctl) SHOULD use a generic parser parameterized
  by field names, not per-query parser functions.

### SQL Safety

The `dns/psql.py` module constructs SQL from user input for psql queries. All user-provided values
(client names, domain patterns, timestamps) MUST be escaped via `sql_escape` before interpolation
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

Reference implementation: `hops app pod` (implemented in `app/pod_detail.py`). One call resolves the
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

## Testing

The test suite at `scripts/hops/tests/` is the primary validation mechanism. All changes to hops
MUST maintain, update, or extend the test suite. Run tests via:

```bash
# All tests (unit + integration against live cluster)
uv run --project scripts/hops pytest scripts/hops/tests/ -v

# Unit tests only (no cluster access needed)
uv run --project scripts/hops pytest scripts/hops/tests/ -v -m "not integration"
```

### Test Categories

**Unit tests** (`test_format.py`, `test_time.py`, `test_dns_psql.py`): Pure function tests for
`core.format`, `core.time`, and `dns.psql`. No cluster access. These test formatting, parsing, and
escaping logic that has caused regressions.

**Resolver integration tests** (`test_resolver.py`): Call `core.resolve.resolve()` directly against
the live cluster. Cover every resource category: Deployment, StatefulSet, DaemonSet, CronJob, CNPG
pods, subchart naming. These are the tests that would have caught the 4 resolver fix commits.

**Command integration tests** (`test_commands.py`): Invoke `./scripts/hops.sh` via subprocess and
assert on exit codes and output structure (header presence, section markers). Cover all domains.

### Test Obligations

When modifying hops code, MUST:

1. Run the full test suite before considering the change complete
2. Fix any test failures caused by the change (update assertions, not delete tests)
3. Add tests for new commands (at minimum: exit 0 for valid input, non-zero for invalid)
4. Add tests for new resolver strategies or resource categories
5. Add unit tests for new pure functions in `core/`
6. Update test fixtures when cluster apps are added or removed

When a test fails due to a removed or renamed cluster app, update the fixture data in the test to
reference a current app. Do not delete the test.

### Test Patterns

- Integration tests are marked `@pytest.mark.integration`
- Use `conftest.run_hops()` for subprocess invocations
- Assert on output structure (headers, section markers), not exact values
- Assert on app names and namespaces (stable); skip pod suffixes and timestamps (volatile)
- Test both success and failure paths (valid app, nonexistent app)

### Verification

```bash
# Verify a specific command works
./scripts/hops.sh <domain> <command>

# Compare token usage vs raw equivalent
./scripts/hops.sh node list 2>&1 | ttok
kubectl get nodes -o wide 2>&1 | ttok
```
