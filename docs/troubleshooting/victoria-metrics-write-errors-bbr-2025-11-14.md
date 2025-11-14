# VictoriaMetrics Remote Write Errors - BBR Congestion & BPF Host Routing

**Date:** 2025-11-14

**Status:** MONITORING - Known BBR/BPF routing issue affecting intra-cluster communication

## Executive Summary

vmagent experiencing timeout errors when writing metrics to vmsingle after Cilium BBR and BPF host
routing enablement (commit 0d0492e). Same root cause as Plex streaming issue: BBR enforcement at pod
networking level interacting poorly with BPF host routing.

**Alert:** RequestErrorsToAPI fires when vmagent->vmsingle communication times out

**Impact:** Metrics ingestion delays, no data loss (vmagent retries with exponential backoff)

**Mitigation:** Monitor for sustained issues, revert BBR/BPF changes if metrics gaps exceed 5
minutes

## Timeline

- **08:47 UTC:** Cilium BBR + BPF host routing enabled (commit 0d0492e)
- **14:49 UTC:** Cilium pods restarted after configuration apply
- **15:09 UTC:** RequestErrorsToAPI alert started firing
- **15:32 UTC:** Issue ongoing with consistent 120s timeout pattern

## Symptoms

### vmagent Logs

```txt
couldn't send a block with size 54766 bytes to "1:secret-url":
Post "http://vmsingle-victoria-metrics-k8s-stack.observability.svc.cluster.local.:8428/api/v1/write":
net/http: request canceled (Client.Timeout exceeded while awaiting headers);
re-sending the block in 65.920 seconds
```

### vmsingle Logs

```txt
remoteAddr: "10.42.3.110:41048"; requestURI: /api/v1/write;
cannot read compressed request in 121 seconds: read tcp4 10.42.1.188:8428->10.42.3.110:41048:
read: connection reset by peer
```

### Alert Details

- **Expression:** `increase(vm_http_request_errors_total[5m]) > 0`
- **Path:** `/api/v1/write`
- **Protocol:** promremotewrite
- **Pods:** vmagent-victoria-metrics-k8s-stack-6c7fdd778-5hdkq →
  vmsingle-victoria-metrics-k8s-stack-57d66f9689-pdltl
- **IPs:** 10.42.3.110 (vmagent) → 10.42.1.188 (vmsingle)

## Root Cause

**Same issue as Plex streaming:** BBR congestion control enforcement via Cilium Bandwidth Manager
combined with BPF host routing (`bpf.hostLegacyRouting: false`) causing timeout issues for
high-throughput sequential writes.

**Technical Details:**

- vmagent writes metrics in batches (54766 bytes observed)
- Timeout occurs after 120-121 seconds (vmagent client timeout)
- Connection reset by peer from vmsingle side
- vmagent retries with exponential backoff (2s, 4s, 8s, 16s, 32s, 65s max)

**Why This Differs from Plex:**

- Plex: External client → pod (crosses node boundaries, NFS involved)
- VictoriaMetrics: Pod → pod (intra-cluster, both on cluster networking)
- Same underlying BBR/BPF routing issue manifests differently

## Investigation Evidence

### Pod Identification

```bash
$ kubectl get pods -A -o wide | rg "10\.42\.3\.110"
observability vmagent-victoria-metrics-k8s-stack-6c7fdd778-5hdkq 2/2 Running 0 42m 10.42.3.110 sakura

$ kubectl get pod -n observability vmsingle-victoria-metrics-k8s-stack-57d66f9689-pdltl -o jsonpath='{.spec.nodeName}'
nami
```

### Timing Correlation

```bash
# Cilium restart after BBR config
$ kubectl get pods -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].status.startTime}'
2025-11-14T14:49:49Z

# Alert started 19 minutes after Cilium restart
Alert: RequestErrorsToAPI
Active Since: 2025-11-14T15:09:00Z
```

### Related Alerts

- **RequestErrorsToAPI:** vmsingle receiving errors on `/api/v1/write`
- **TooManyRemoteWriteErrors:** vmagent retry count increasing

## Current Configuration

### Cilium (commit 0d0492e)

```yaml
bandwidthManager:
  enabled: true
  bbr: true
bpf:
  hostLegacyRouting: false
```

### Talos Sysctls

```yaml
net.core.rmem_max: "67108864"
net.core.wmem_max: "67108864"
net.ipv4.tcp_rmem: "4096 262144 67108864"
net.ipv4.tcp_wmem: "4096 262144 67108864"
net.ipv4.tcp_congestion_control: "bbr"
net.ipv4.tcp_fastopen: "3"
net.core.default_qdisc: "fq"
net.ipv4.tcp_mtu_probing: "1"
```

### VictoriaMetrics Resources

**vmsingle:**

- Memory: 952Mi / 4Gi (not resource constrained)
- Node: nami
- Storage: openebs-hostpath (30Gi RWO)

**vmagent:**

- Memory: 512Mi limit
- Node: sakura
- Remote write URL:
  `http://vmsingle-victoria-metrics-k8s-stack.observability.svc.cluster.local.:8428/api/v1/write`

## Impact Assessment

### Data Loss Risk

**LOW** - vmagent implements retry logic with exponential backoff:

- Retries failed blocks indefinitely until success
- Uses persistent queue for failed writes
- Maximum backoff: 65.920 seconds between retries
- No data loss observed, only ingestion delays

### Alert Noise

**MEDIUM** - RequestErrorsToAPI fires continuously while issue persists

### Metrics Gaps

**VARIABLE** - Depends on retry success rate:

- Short gaps (1-2 minutes): Acceptable, queries still work
- Extended gaps (5+ minutes): Indicates sustained failure, requires intervention

## Monitoring

### Key Metrics

**vmagent retry rate:**

```promql
rate(vmagent_remotewrite_retries_count_total[5m]) > 0
```

**Request error rate:**

```promql
increase(vm_http_request_errors_total{path="/api/v1/write"}[5m])
```

**Queue size:**

```promql
vmagent_remotewrite_pending_data_bytes
```

### Validation Commands

**Check vmagent retry count:**

```bash
kubectl exec -n observability deploy/vmagent-victoria-metrics-k8s-stack -c vmagent -- \
  wget -qO- localhost:8429/metrics | rg "vmagent_remotewrite_retries_count_total"
```

**Check vmsingle errors:**

```bash
kubectl logs -n observability deploy/vmsingle-victoria-metrics-k8s-stack --tail=50 | rg -i "error|warn"
```

**Check alert status:**

```bash
./scripts/vmalert-query.py detail RequestErrorsToAPI
```

## Remediation Options

### Option 1: Monitor (CURRENT)

Wait for BBR/BPF routing stabilization, monitor for extended metrics gaps

**When to escalate:** Metrics gaps exceed 5 minutes consistently

### Option 2: Increase vmagent Timeout

Increase vmagent client timeout to tolerate slower writes

**Tradeoff:** Longer delays before retry, may mask underlying issues

### Option 3: Revert BBR/BPF Changes

Revert Cilium to previous configuration:

```yaml
bandwidthManager:
  enabled: false
bpf:
  hostLegacyRouting: true
```

**When:** If monitoring shows sustained failures impacting observability

### Option 4: Silence Alert

If monitoring confirms data integrity (no gaps), silence alert as known issue

**Requires:** Verification that vmagent retries always succeed eventually

## Related Issues

- **Plex Streaming Stuttering:** [plex-streaming-stuttering-bbr-congestion-2025-11-13.md][plex-doc]
- **Cilium BBR Commit:** 0d0492e49c20f967e7b708e27ad1de3bbd1b8f61
- **Talos DNS Bug:** [siderolabs/talos#10002][talos-10002] (different symptom, same config)

[plex-doc]: plex-streaming-stuttering-bbr-congestion-2025-11-13.md
[talos-10002]: https://github.com/siderolabs/talos/issues/10002

## Investigation Commands Reference

### Alert Queries

```bash
# Check all firing alerts
./scripts/vmalert-query.py firing

# Get RequestErrorsToAPI details
./scripts/vmalert-query.py detail RequestErrorsToAPI
```

### vmagent Diagnostics

```bash
# Check vmagent logs
kubectl logs -n observability vmagent-victoria-metrics-k8s-stack-6c7fdd778-5hdkq -c vmagent --tail=100

# Check retry metrics
kubectl exec -n observability deploy/vmagent-victoria-metrics-k8s-stack -c vmagent -- \
  wget -qO- localhost:8429/metrics | rg "remotewrite"
```

### vmsingle Diagnostics

```bash
# Check vmsingle logs
kubectl logs -n observability deploy/vmsingle-victoria-metrics-k8s-stack --tail=100

# Check resource usage
kubectl top pod -n observability vmsingle-victoria-metrics-k8s-stack-57d66f9689-pdltl
```

### Network Analysis

```bash
# Check active connections from vmagent pod
kubectl exec -n observability vmagent-victoria-metrics-k8s-stack-6c7fdd778-5hdkq -c vmagent -- \
  netstat -tn | rg 8428

# Check TCP state from sakura node
kubectl debug node/sakura -it --image=nicolaka/netshoot -- \
  ss -ti dst 10.42.1.188:8428
```

## Next Steps

1. Monitor metrics gaps for 24-48 hours
2. Check if issue self-resolves as BBR stabilizes
3. Correlate with Plex streaming behavior (same BBR impact)
4. If sustained failures: Consider reverting BBR or adjusting vmagent timeouts
5. Document resolution in this file

## Document Status

**Created:** 2025-11-14 **Last Updated:** 2025-11-14 **Status:** MONITORING - Issue ongoing, data
integrity intact, awaiting stabilization
