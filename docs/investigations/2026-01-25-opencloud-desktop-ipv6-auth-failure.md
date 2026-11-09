# OpenCloud Desktop OAuth Failure - IPv6 CNAME Chain Leak

- **Date:** 2026-01-25
- **Status:** RESOLVED (original AdGuard fix superseded by Blocky migration; see [ADR-004][adr-004])

## Summary

OpenCloud Desktop OAuth authentication fails intermittently with "Network unreachable" when
exchanging the authorization code for tokens. Root cause: UDMP forwards DNS queries for record types
it doesn't have locally (AAAA, HTTPS) to upstream Cloudflare, which returns CNAME chains pointing to
tunnel IPv6 addresses unreachable from the LAN. Original fix was AdGuard filtering rules; now
handled natively by Blocky's `filterUnmappedTypes` default.

[adr-004]: /docs/decisions/004-blocky-dns-migration.md

## Symptoms

- OpenCloud Desktop prompts for reauthentication
- Browser OAuth flow completes successfully (user signs in via pocket-id)
- Browser redirects to `http://127.0.0.1:<port>/?code=...` - localhost callback succeeds
- Error page displays: "Login Error - There was an error accessing the 'token' endpoint: Network
  unreachable"
- Issue is intermittent - resolves temporarily after flushing DNS cache

## Technical Root Cause Analysis

### DNS Architecture Context

The homelab uses split-horizon DNS (see [DNS Architecture][dns-arch]):

- **Internal clients**: AdGuard Home (192.168.50.71) with conditional forwarding to UDMP
  (192.168.1.1) for `*.domain.com`
- **External clients**: Cloudflare DNS resolves to Cloudflare Tunnel

UDMP local DNS records:

```txt
external.domain.com    A    192.168.50.73
internal.domain.com    A    192.168.50.72
auth.domain.com        CNAME external.domain.com (managed by external-dns)
```

Cloudflare DNS records:

```txt
external.domain.com    CNAME    <tunnel-id>.cfargotunnel.com
```

### The Leak Path

1. Client application calls `getaddrinfo("auth.domain.com")`
2. systemd-resolved queries AdGuard for multiple record types in parallel: A, AAAA, HTTPS
3. AdGuard forwards `*.domain.com` queries to UDMP (conditional forwarding)
4. UDMP has local A record, returns `192.168.50.73` for A queries
5. UDMP does NOT have local AAAA or HTTPS records
6. UDMP forwards AAAA/HTTPS queries to its upstream DNS (Cloudflare)
7. Cloudflare returns: `external.domain.com CNAME <tunnel-id>.cfargotunnel.com`
8. Resolver follows CNAME chain, queries `cfargotunnel.com` for AAAA
9. Cloudflare returns IPv6: `fd10:aec2:5dae::` (tunnel private IPv6)
10. systemd-resolved caches the CNAME and IPv6
11. Application receives both IPv4 and IPv6 addresses
12. Qt network stack (used by OpenCloud) attempts IPv6 first
13. Connection fails immediately - IPv6 not routable from LAN

### Evidence from Debug Logs

systemd-resolved debug logging (`resolvectl log-level debug`) captured:

```txt
Cache miss for external.domain.com IN HTTPS
Firing regular transaction for <external.domain.com IN HTTPS>
...
Added positive cache entry for external.domain.com IN CNAME 300s
Following CNAME/DNAME external.domain.com → <tunnel-id>.cfargotunnel.com
...
Positive cache hit for external.domain.com IN AAAA
```

OpenCloud logs (`/tmp/OpenCloud-logdir/OpenCloud.log`):

```txt
REQUEST POST https://auth.domain.com/api/oidc/token
RESPONSE error: "Network unreachable", status: 0, duration: 0ms
```

### Why UDMP Forwards Upstream

UDMP only stores A records locally. Verified with `+norecurse`:

```bash
$ dig external.domain.com @192.168.1.1 A +norecurse
;; flags: qr aa ra    # 'aa' = authoritative answer
external.domain.com.  0  IN  A  192.168.50.73

$ dig external.domain.com @192.168.1.1 AAAA +norecurse
;; status: SERVFAIL
;; EDE: 0 (Other): (no local cache to fulfill non recursion request)
```

When recursion is enabled (default), UDMP forwards queries it cannot answer locally to its upstream
DNS (Cloudflare), which returns the tunnel CNAME chain.

### Why This Is Intermittent

The CNAME and IPv6 records have TTLs (typically 300s). When cached:

- `getent ahosts auth.domain.com` returns IPv6 from cache
- Applications fail with "Network unreachable"

After cache expires or manual flush:

- Fresh query gets only IPv4 (AAAA blocked at AdGuard)
- Applications work correctly

## Solution

### AdGuard Custom Filtering Rules

Block AAAA and HTTPS queries for `domain.com` at AdGuard before they reach UDMP:

```txt
||domain.com^$dnstype=AAAA,dnsrewrite=REFUSED
||domain.com^$dnstype=HTTPS,dnsrewrite=REFUSED
```

This ensures:

- A queries flow normally: AdGuard → UDMP → local A record
- AAAA queries blocked at AdGuard with REFUSED response
- HTTPS queries blocked at AdGuard with REFUSED response
- No queries leak to Cloudflare via UDMP upstream forwarding

### Verification

```bash
# AAAA should return REFUSED (empty with +short)
$ dig external.domain.com @192.168.50.71 AAAA
;; status: REFUSED

# HTTPS should return REFUSED
$ dig external.domain.com @192.168.50.71 HTTPS
;; status: REFUSED

# A record should still work
$ dig external.domain.com @192.168.50.71 A +short
192.168.50.73

# Full resolution should be IPv4 only
$ resolvectl flush-caches
$ getent ahosts auth.domain.com
192.168.50.73   STREAM external.domain.com
192.168.50.73   DGRAM
192.168.50.73   RAW
```

## Alternatives Considered

### UDMP Native Solutions

Research confirmed UDMP cannot:

- Return NXDOMAIN for record types without local entries
- Disable recursive forwarding for specific domains
- Be configured as authoritative for all record types

The only UDMP option is "Forward Domain" which redirects to another DNS server, creating circular
dependencies with AdGuard.

### AdGuard DNS Rewrites

Alternative to blocking - make AdGuard authoritative:

```txt
||external.domain.com^$dnsrewrite=192.168.50.73
||internal.domain.com^$dnsrewrite=192.168.50.72
```

Rejected because it duplicates UDMP configuration and bypasses external-dns management.

### System-Wide IPv6 Disable

```bash
sysctl -w net.ipv6.conf.all.disable_ipv6=1
```

Rejected - overly broad, affects all applications.

### /etc/hosts Entries

```txt
192.168.50.73 auth.domain.com
192.168.50.73 external.domain.com
```

Rejected - requires maintenance on each client, not centrally managed.

## Investigation Commands

### Check Current Resolution State

```bash
# What the system resolver returns
getent ahosts auth.domain.com

# What's in systemd-resolved cache
resolvectl query auth.domain.com

# Flush cache if poisoned
resolvectl flush-caches
```

### Test AdGuard Filtering

```bash
# Direct query to AdGuard
dig external.domain.com @192.168.50.71 A +short
dig external.domain.com @192.168.50.71 AAAA +short   # Should be empty
dig external.domain.com @192.168.50.71 HTTPS +short  # Should be empty
```

### Test UDMP Behavior

```bash
# What UDMP returns with recursion (will forward upstream)
dig external.domain.com @192.168.1.1 AAAA +short

# What UDMP has locally (no forwarding)
dig external.domain.com @192.168.1.1 AAAA +norecurse
```

### Enable systemd-resolved Debug Logging

```bash
# Enable (requires root/pkexec)
pkexec resolvectl log-level debug

# Watch logs
journalctl -f -u systemd-resolved | rg "dailey"

# Disable when done
pkexec resolvectl log-level info
```

### Check OpenCloud Logs

```bash
cat /tmp/OpenCloud-logdir/OpenCloud.log | tr -d '\0' | rg -i "token|unreachable|error"
```

## References

- [DNS architecture documentation][dns-arch]
- [ADR-004: Blocky DNS migration][adr-004] (supersedes AdGuard-specific fix via
  `filterUnmappedTypes`)

[dns-arch]: /docs/architecture/dns-architecture.md
