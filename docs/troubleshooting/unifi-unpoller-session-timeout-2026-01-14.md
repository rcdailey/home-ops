# UniFi Unpoller Session Timeout Investigation - 2026-01-14

**Last Updated:** 2026-01-14

**Status:** ROOT CAUSE IDENTIFIED - UNIFI SESSION EXPIRY

## Executive Summary

VMAlert `UnifiLinkSpeedDegraded1G` alerts were firing, resolving, and re-firing every 2 hours
despite the underlying condition remaining true. Investigation revealed UniFi OS terminates API
sessions every 2 hours, causing unpoller to briefly lose authentication and metrics to disappear.

**PRIMARY CAUSE:** UniFi OS hardcoded 2-hour session timeout for username/password authentication.
When session expires, unpoller gets 401 Unauthorized, metrics briefly disappear, VMAlert resets the
`for` timer, and Alertmanager sends both "resolved" and "firing" notifications.

**SOLUTION:** Switch unpoller from username/password to API key authentication. API keys don't have
session expiry and provide stable, long-lived authentication.

## Symptoms

User observed in Pushover notifications (newest to oldest):

```txt
- UnifiLinkSpeedDegraded1G fired at 7:58
- UnifiLinkSpeedDegraded1G resolved at 7:58
- UnifiLinkSpeedDegraded1G fired at 5:58
- UnifiLinkSpeedDegraded1G resolved at 5:57
- UnifiLinkSpeedDegraded1G fired at 3:57
- UnifiLinkSpeedDegraded1G resolved at 3:57
```

Pattern: Alert fires and resolves within the same minute, then repeats exactly 2 hours later.

## Root Cause Analysis

### 1. Alert Timing Investigation

Queried `ALERTS_FOR_STATE` metric to find when alert `for` timer was resetting:

```txt
Alert restart times:
2026-01-13 23:54:00 CST
2026-01-14 01:54:30 CST  (2h later)
2026-01-14 03:55:00 CST  (2h later)
```

The alert condition (`port_speed < 1Gbps`) was continuously true, but the `for` timer kept resetting
every 2 hours.

### 2. Unpoller Logs

```log
2026/01/14 03:54:26 [ERROR] metric fetch failed: unifi.GetSites(): controller:
  https://192.168.1.1/proxy/network/api/stat/sites: 401 Unauthorized
2026/01/14 05:54:56 [ERROR] metric fetch failed: 401 Unauthorized
2026/01/14 07:55:26 [ERROR] metric fetch failed: 401 Unauthorized
```

Unpoller was getting 401 errors at exactly the times the alerts were resetting.

### 3. UniFi UDMP nginx-access.log

SSH to UDMP confirmed the session expiry pattern:

```log
03:54:25 401 "GET /proxy/network/api/stat/sites" user="-"      # Session expired
03:54:26 200 "POST /api/auth/login"              user="-"      # Re-authenticate
03:54:55 200 "GET /proxy/network/api/stat/sites" user="Unifi Poller"  # Working again

05:54:55 401 "GET /proxy/network/api/stat/sites" user="-"      # Session expired again
05:54:56 200 "POST /api/auth/login"              user="-"      # Re-authenticate

07:55:25 401 "GET /proxy/network/api/stat/sites" user="-"      # Session expired again
```

**Key Finding:** UniFi OS expires username/password sessions every 2 hours. This is hardcoded
behavior and not configurable.

### 4. Impact on Alerting

When the 401 occurs:

1. Unpoller fails to fetch metrics
2. Metric series goes stale briefly (no data points)
3. VMAlert sees the alert condition as "no data" instead of "true"
4. The `for` timer resets
5. Unpoller re-authenticates and metrics return
6. Alert starts the `for` period again
7. Alert fires as a "new" alert
8. Alertmanager sends both "resolved" (old identity) and "firing" (new identity) notifications

## Solution

### Switch to API Key Authentication

UnPoller supports UniFi API key authentication since v2.14.0 (current version is v2.21.0). API keys
don't have session expiry.

**Configuration change:**

```yaml
# Remove username/password:
# UP_UNIFI_DEFAULT_USER: "..."
# UP_UNIFI_DEFAULT_PASS: "..."

# Add API key:
UP_UNIFI_DEFAULT_API_KEY: "<api-key-from-infisical>"
```

API key is mutually exclusive with username/password - use one or the other.

**To create an API key on UniFi:**

1. UniFi OS Settings -> Admins & Users
2. Select the local user account (or create a dedicated read-only account)
3. Under "Control Plane API", create an API key
4. Use "Read Only" permission level (sufficient for monitoring)
5. Store the API key in Infisical at `/observability/unpoller/api-key`

### Alternative: Add `keep_firing_for` to Alert Rules

If API key migration isn't immediately feasible, add `keep_firing_for` to bridge brief metric gaps:

```yaml
- alert: UnifiLinkSpeedDegraded1G
  expr: unpoller_device_port_port_speed_bps{port_name=~".+-1G"} < 1000000000
  for: 2m
  keep_firing_for: 15m  # Prevents resolve during brief auth gaps
```

This keeps the alert in firing state for 15 minutes after the condition becomes false/absent,
preventing the flapping notifications. However, this is a workaround - API key auth is the proper
fix.

## GitHub Issue Reference

- [unpoller/unpoller#765](https://github.com/unpoller/unpoller/issues/765): "UnPoller - API Key
  (Early Access)" - Feature request that led to API key support. Discussion confirms session timeout
  issues with username/password auth on UDM Pro devices.

## Key Commands Used

### Query Alert State History

```bash
./scripts/query-vm.py query 'ALERTS_FOR_STATE{alertname="UnifiLinkSpeedDegraded1G"}' --from 12h
```

### Check Unpoller Logs

```bash
kubectl logs -n observability deploy/unpoller --since=6h | rg "401|error"
```

### Check UniFi nginx Logs (via SSH)

```bash
ssh unifi "grep -E '03:54|05:54|07:55' /data/unifi-core/logs/nginx-access.log"
```

## Document History

| Date       | Changes                                                |
|------------|--------------------------------------------------------|
| 2026-01-14 | Initial investigation of 2-hour alert flapping pattern |
