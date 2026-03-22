# Replace In-Cluster MCP Sidecar with Local stdio Transport

- **Status:** Accepted
- **Date:** 2026-03-21
- **Decision:** Remove the mcp-searxng sidecar from the SearXNG pod and use npx stdio transport
  instead

## Context and Problem Statement

The mcp-searxng MCP server runs as a sidecar container in the SearXNG pod, exposed via HTTPRoute
through the Envoy gateway. OpenCode connects to it over Streamable HTTP. After roughly 15 to 30
minutes of idle time, the MCP server disappears from OpenCode's context. Tools become unavailable
and only a full restart recovers the session. This is the same class of problem that led to
[ToolHive removal][adr-010], now occurring without any intermediary.

## Considered Options

- **Keep sidecar, fix server-side keepalives** - Add SSE keepalive comments to prevent proxy idle
  timeouts from killing the notification stream
- **Keep sidecar, fix client-side reconnection** - Wait for OpenCode to merge retry/reconnect PRs
  ([#17651][pr-17651], [#17153][pr-17153]) that prevent permanent eviction on transient failure
- **Switch to stdio transport** - Run mcp-searxng locally via npx, communicating over stdin/stdout
  with no network involvement

## Decision Outcome

Chosen option: **Switch to stdio transport**, because the root cause is not in the cluster
infrastructure. Investigation ruled out Envoy (all timeout counters zero, stream idle timeout
configured at 86400s) and the MCP server (sessions persist indefinitely in memory, pod stable with
zero restarts). The actual cause is Bun's native `fetch()` imposing an implicit timeout on streaming
responses ([oven-sh/bun#16682][bun-16682]). OpenCode works around this for AI provider streams
(`timeout: false` in `provider.ts:1279`) but does not apply the same fix to MCP transport
connections.

Server-side keepalives were implemented and confirmed working (SSE comments every 30 seconds), but
they cannot prevent the client runtime from aborting its own fetch. The OpenCode fix PRs address the
symptom (permanent eviction on failure) but not the root cause (Bun killing the stream). Both are
upstream changes outside our control with unknown merge timelines.

The stdio transport eliminates the entire network stack from the equation: no SSE streams, no Bun
fetch timeouts, no proxy idle timeouts, no session management. The SearXNG instance remains
accessible via its existing HTTPRoute at `search.${SECRET_DOMAIN}`.

## Consequences

- Good, because MCP sessions no longer drop during idle periods
- Good, because removes sidecar container, MCP service, and MCP HTTPRoute from the pod
- Good, because no dependency on upstream OpenCode or MCP SDK fixes
- Bad, because MCP server runs locally instead of in-cluster (acceptable for single-user)
- Bad, because server-side keepalive work (SDK fork, mcp-searxng v2 migration) is shelved

## References

- [OpenCode: MCP tools permanently lost after transient failure][pr-17099]
- [OpenCode: retry listTools before evicting (PR)][pr-17153]
- [OpenCode: recover clients after transient failures (PR)][pr-17651]
- [OpenCode: auto-reconnect remote MCP servers on idle timeout][issue-15247]
- [Bun: fetch implicit timeout on streaming responses][bun-16682]
- [ADR-010: ToolHive removal][adr-010]

[pr-17099]: https://github.com/anomalyco/opencode/issues/17099
[pr-17153]: https://github.com/anomalyco/opencode/pull/17153
[pr-17651]: https://github.com/anomalyco/opencode/pull/17651
[issue-15247]: https://github.com/anomalyco/opencode/issues/15247
[bun-16682]: https://github.com/oven-sh/bun/issues/16682
[adr-010]: /docs/decisions/010-toolhive-removal.md

## Historical Context

After removing ToolHive ([ADR-010][adr-010]), MCP servers were configured as in-cluster sidecars to
avoid the intermediary complexity. The SearXNG pod ran mcp-searxng as a second container, exposed on
a dedicated service and HTTPRoute (`mcp-search.${SECRET_DOMAIN}`).

### Investigation (Mar 21)

Comprehensive analysis of the full request chain:

1. **Envoy Gateway (ruled out):** All timeout counters at zero (`upstream_cx_idle_timeout`,
   `upstream_rq_timeout`, `downstream_rq_idle_timeout`, `upstream_cx_max_duration_reached`).
   ClientTrafficPolicy correctly sets `streamIdleTimeout: 86400s`. BackendTrafficPolicy disables
   request timeout (`0s`). EG v1.7.1 handles the interaction correctly post-PR #8058.

2. **MCP server (ruled out):** Sessions stored in an in-memory map with no TTL or expiration.
   `Protocol.connect()` wraps (not overwrites) the `transport.onclose` callback, preserving session
   cleanup. Pod stable at zero restarts for days.

3. **Server-side keepalives (implemented, insufficient):** Forked the MCP TypeScript SDK to add
   `keepAliveInterval` to `WebStandardStreamableHTTPServerTransport`. Forked mcp-searxng, migrated
   to SDK v2, and enabled 30-second keepalive comments. Confirmed working via direct SSE stream
   test. Did not resolve the problem because the client runtime kills the fetch before any proxy
   would.

4. **Root cause found in OpenCode client:** Bun's `fetch()` has an implicit timeout on streaming
   responses. OpenCode's AI provider layer sets `timeout: false` to work around this (referencing
   `oven-sh/bun#16682`), but the MCP `StreamableHTTPClientTransport` instantiation at
   `mcp/index.ts:365` uses default fetch without this override. When the timeout fires, the SSE
   stream dies. The SDK attempts reconnection (`maxRetries: 2`) but the session ID may be stale if
   the pod was replaced. OpenCode then calls `listTools()`, catches the error, and permanently
   deletes the server from its client map (`mcp/index.ts:626-627`) with no retry or reconnection.
