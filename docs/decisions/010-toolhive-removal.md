# Remove ToolHive MCP Server Orchestration

- **Status:** Accepted
- **Date:** 2026-03-03
- **Decision:** Remove ToolHive and return to directly-configured MCP servers

## Context and Problem Statement

MCP servers orchestrated by ToolHive (Context7, SearXNG) intermittently disappear from active
OpenCode sessions due to connectivity and session lifecycle problems. The only recovery is a full
OpenCode restart, which disrupts development workflow. Despite contributing upstream fixes, the
platform never reached reliable steady-state over a month of production use.

## Considered Options

- **Remove ToolHive, configure MCP servers directly** - Eliminate the intermediary; connect OpenCode
  to MCP servers without the operator/proxy/gateway stack
- **Keep ToolHive, opt in to session management V2** - Enable the `sessionManagementV2` feature flag
  introduced in [#3906][pr-3906] (landed 2026-03-03) and wait for proxy fixes to stabilize
- **Keep ToolHive, continue patching locally** - Maintain a local fork with session TTL and eviction
  logging changes

## Decision Outcome

Chosen option: **Remove ToolHive, configure MCP servers directly**, because the intermediary
architecture (operator, proxy, gateway) introduces failure modes that do not exist with direct
configuration. Session management V2 is behind a feature flag, explicitly marked as incompatible
with some features, and has zero production soak time. The proxy mutex and idle timeout fixes
([#3970][pr-3970]) also landed the same day with no soak time.

Direct MCP server configuration is simpler, has no session eviction semantics, and provides the same
functionality without the orchestration overhead.

## Consequences

- Good, because MCP sessions no longer silently drop during active use
- Good, because eliminates operator/proxy/gateway maintenance burden (5 renovate PRs in one month)
- Good, because removes the mcp-images CI workflow and dockyard container build pipeline
- Bad, because loses centralized MCP server lifecycle management
- Bad, because per-server configuration must be maintained individually
- Bad, because cannot revisit without redeploying the full stack

## References

- [Upstream SPDY EOF bug report][issue-3583]
- [SPDY EOF fix (contributed)][pr-3584]
- [Session management V2 phase 1][pr-3882]
- [Session management V2 phase 2][pr-3906]
- [Proxy mutex deadlock fix][pr-3970]
- [Container restart vs exit distinction][pr-3937]

[issue-3583]: https://github.com/stacklok/toolhive/issues/3583
[pr-3584]: https://github.com/stacklok/toolhive/pull/3584
[pr-3882]: https://github.com/stacklok/toolhive/pull/3882
[pr-3906]: https://github.com/stacklok/toolhive/pull/3906
[pr-3937]: https://github.com/stacklok/toolhive/pull/3937
[pr-3970]: https://github.com/stacklok/toolhive/pull/3970

## Historical Context

ToolHive was deployed on 2026-02-03 to orchestrate MCP servers in-cluster via the toolhive-operator.
The integration included the operator (CRDs + controller), MCPServer resources for Context7 and
SearXNG, a VirtualMCPServer gateway, and a CI workflow to build MCP container images using `thv
build`.

### SPDY EOF zombie state (Feb 4)

Within 24 hours, proxies began entering a zombie state. SPDY attach connections to workload pods
silently died after approximately 12 minutes idle. The proxy continued running and passing health
checks, but could not communicate with MCP workloads. The gateway timed out trying to reach
backends, and MCP tools failed to register for new client sessions.

Root cause was three bugs in `AttachToWorkload()`: SPDY executor reuse across retries (corrupted
state after EOF), no per-attempt timeout (blocked forever on dead connections), and unclosed stdio
pipes on goroutine exit. Filed [#3583][issue-3583] with detailed analysis and contributed the fix in
[#3584][pr-3584], which was merged 2026-02-05. Ran the fix in production for 9 hours before marking
it ready; went from 100+ proxy restarts to zero.

### Continued session drops (Feb-Mar)

After the SPDY fix, MCP servers still disappeared from active OpenCode sessions. Investigation
traced the root cause to the upstream 30-minute default session TTL (`defaultSessionTTL = 30 *
time.Minute` in `pkg/vmcp/server/server.go`). Sessions were silently evicted during normal use, with
no client notification or reconnection mechanism.

Began patching locally: configurable `SessionTTL` in the operational config (defaulting to 8h),
wiring through `commands.go` to the server, and adding eviction logging to `storage_local.go`. This
work was abandoned when it became clear the fix required broader upstream changes to session
lifecycle management.

### Upstream response (Mar 2-3)

The ToolHive team began a ground-up rewrite of session management (RFC THV-0038), landing Phase 1
([#3882][pr-3882]) and Phase 2 ([#3906][pr-3906]) with a new `vmcpSessionManager` behind a feature
flag. Separately, proxy stability fixes addressed the mutex deadlock during shutdown
([#3970][pr-3970]) and container restart detection ([#3937][pr-3937]). These changes are encouraging
but have no production soak time and are not yet default behavior. If the feature flag is removed
and session V2 stabilizes, this decision may be worth revisiting.
