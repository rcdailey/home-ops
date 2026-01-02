---
name: querying-metrics
description: Queries VictoriaMetrics for metrics and alerts, queries VictoriaLogs for logs. Use when checking CPU/memory usage, viewing firing alerts, running PromQL, or searching application logs.
---

# Querying Metrics and Logs

## Metrics and Alerts

Run `scripts/query-vm.py`. Add `--json` before subcommand for machine output.

```bash
# Container resource usage (namespace, pod-regex, container, duration)
scripts/query-vm.py cpu media 'plex.*' plex 7d
scripts/query-vm.py memory default 'homepage.*' app 24h

# Raw PromQL
scripts/query-vm.py query 'up{job="kubelet"}'
scripts/query-vm.py query 'rate(http_requests_total[5m])' --range \
  --start <ISO8601> --end <ISO8601>

# Label/metric discovery
scripts/query-vm.py labels
scripts/query-vm.py labels namespace
scripts/query-vm.py metrics --filter cpu

# Alerts
scripts/query-vm.py alerts                  # Firing only
scripts/query-vm.py alerts --state all
scripts/query-vm.py alert <name>
scripts/query-vm.py history 24h             # Firing frequency
```

## Logs

Run `scripts/query-victorialogs.py`.

```bash
# By app/namespace
scripts/query-victorialogs.py --app cloudflare-tunnel -10
scripts/query-victorialogs.py --app kometa --level error -20
scripts/query-victorialogs.py --namespace observability --start 5m

# LogSQL queries
scripts/query-victorialogs.py "error" --start 1h --limit 50
scripts/query-victorialogs.py '{app="nginx"} AND error' --start 5m
scripts/query-victorialogs.py --stats "error | stats by(level) count(*)"
```
