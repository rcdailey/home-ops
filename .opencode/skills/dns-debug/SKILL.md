---
name: dns-debug
description: >-
  Use when diagnosing DNS issues, investigating blocked domains, or debugging website connectivity
  problems reported by users
---

# DNS Debugging

Diagnose DNS resolution failures using Blocky query logs stored in PostgreSQL. Primary scenario: a
user reports a website is broken and you need to determine whether Blocky is blocking a required
domain.

## Tool

`./scripts/query-blocky.py` queries the `log_entries` table in the Blocky CNPG PostgreSQL cluster
via `kubectl exec`.

Run `./scripts/query-blocky.py --help` for full usage.

### Quick Reference

```bash
# Search: who queried a domain recently?
./scripts/query-blocky.py search homedepot --from 24h

# Logs: all queries from a specific client
./scripts/query-blocky.py logs --client 192.168.3.40 --from 1h

# Blocked: only blocked queries for a client
./scripts/query-blocky.py blocked --client 192.168.3.40 --from 1h

# Combine filters
./scripts/query-blocky.py logs --client 192.168.3.40 --domain homedepot --from 2h

# VLAN shorthand (lan, iot, kids, guest, work, cameras)
./scripts/query-blocky.py blocked --client kids --from 24h

# Machine-readable
./scripts/query-blocky.py --json blocked --client 192.168.3.40
```

## Diagnostic Workflow

When a user reports "website X is broken":

1. **Search for the domain** to identify the client device: `./scripts/query-blocky.py search
   <domain> --from 24h` Pick the client with the most recent `last_seen` timestamp.

2. **Get blocked queries for that client** to find the offending domain: `./scripts/query-blocky.py
   blocked --client <ip> --from 1h` The blocked domain is often not the main site but a subdomain
   (API, CDN, auth service).

3. **Verify the block** by checking the `reason` field. It indicates which blocklist group matched
   (e.g., `ads`, `threats`, `social`).

4. **Determine the fix** (see Remediation below).

5. **After pushing the fix**, Flux applies the change and Blocky reloads automatically (reloader
   annotation). Verify resolution: `./scripts/query-blocky.py logs --client <ip> --domain <domain>
   --from 5m` The domain should now show `RESOLVED` or `CACHED` instead of `BLOCKED`.

## Remediation

### Option A: Add an allowlist entry (single domain fix)

Add an `allowlists` section to the blocking config in
`kubernetes/apps/dns-private/blocky/data/config.yaml`. The allowlist group name must match the
denylist group that blocked the domain.

```yaml
blocking:
  denylists:
    ads:
    - https://...
  allowlists:
    ads:
    - |
      alloweddomain.com
      api.someservice.com
```

Allowlists take precedence over denylists within the same group. A domain present in both the deny
and allow list for a group will be allowed.

### Option B: Switch to a less aggressive blocklist

If false positives are frequent for a list category, consider switching to a less aggressive
variant. Read the current config to identify which list tier is in use, then check upstream for
available tiers.

### Option C: Remove a blocklist group from a client group

If an entire category is causing problems for a VLAN, remove it from `clientGroupsBlock` for that
VLAN.

## Configuration Reference

Read `kubernetes/apps/dns-private/blocky/data/config.yaml` for current:

- VLAN-to-subnet mappings and which block groups apply to each
- Denylist URLs and their group names
- Any existing allowlist entries

## Unimplemented Subcommands

The following subcommands were deferred. If you need one during diagnosis, implement it in
`./scripts/query-blocky.py` following the patterns of the existing subcommands, then update this
skill file to move it from this list to the Quick Reference section above.

- **top-domains**: Top queried domains by count. Flags: `--from`, `--client`, `--limit`. GROUP BY
  `question_name`, ORDER BY count DESC.
- **top-blocked**: Top blocked domains by count. Same as top-domains but filtered to
  `response_type = 'BLOCKED'`. Include the `reason` column to show which blocklist group matched.
- **top-clients**: Top clients by query volume. Flags: `--from`, `--limit`. GROUP BY `client_ip`,
  `client_name`, ORDER BY count DESC.
- **slow**: Queries exceeding a duration threshold. Flags: `--from`, `--client`, `--threshold`
  (milliseconds, default 500). Filter `duration_ms >= threshold`, ORDER BY `duration_ms` DESC.

## Pattern Detection

When adding allowlist entries, check git history for systemic issues:

```bash
git log --oneline -- kubernetes/apps/dns-private/blocky/data/config.yaml
```

If you see 3+ allowlist additions in a short period, the denylist tier may be too aggressive.
Propose downgrading the list tier rather than maintaining a growing allowlist.
