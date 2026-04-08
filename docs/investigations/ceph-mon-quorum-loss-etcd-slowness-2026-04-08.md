# Ceph Mon Quorum Loss Coinciding with etcd Slowness

- **Date:** 2026-04-08
- **Status:** UNRESOLVED (paused pending diagnostic improvements)

## Summary

Leader-elected controllers across the cluster (silence-operator, kube-controller-manager,
cloudnative-pg, keda-operator, external-secrets-cert-controller, snapshot-controller, openebs,
ceph-csi-controller-manager, and others) periodically lose their leader leases and restart.
Investigation traced the proximate cause to Kubernetes API server write slowness during brief
windows when etcd on hanekawa (the Raft leader) has p99 GET/LIST latency spikes of 21-25 seconds.
These etcd spikes consistently coincide with Ceph mon quorum loss events (4 on hanekawa's mon-j, 1
on marin's mon-m over 4 days). Root cause of the coincident etcd/Ceph disturbance is not yet
identified. Ceph cluster itself is HEALTH_OK; no hardware errors surfaced; host resource metrics
show no saturation during incident windows. Investigation paused to first improve diagnostic
visibility so future incident windows can be analyzed with better data.

## Symptoms

### Observable

- **Leader-elected pods restart** with `leader election lost` / `context deadline exceeded` errors.
  Restart counts as of 2026-04-08:
  - cloudflare-tunnel: 139 (likely unrelated, app-specific)
  - cloudflare-dns: 87 (likely unrelated, app-specific)
  - openebs-localpv-provisioner: 25
  - node-feature-discovery-master: 15
  - snapshot-controller: 11
  - external-secrets-cert-controller: 11
  - ceph-csi-controller-manager: 10
  - silence-operator: 9
  - keda-operator: 8
  - cloudnative-pg: 8
  - grafana-operator: 7
  - kube-controller-manager-marin: 7
  - external-secrets: 6
  - rook-ceph-mon-j: 7 (mon container; restart pattern described below)
  - Several at 3-5 (mariadb-operator, envoy-gateway, pocket-id-operator, VM operator,
    kube-controller-manager-hanekawa, kube-scheduler-hanekawa, etc.)

- **Kubernetes API server write latency spikes.** p99 latency on PUT/PATCH verbs reaches 5-7
  seconds during incident windows (normal: 40-900ms).

- **etcd GET/LIST latency spikes.** From `etcd_request_duration_seconds_bucket` (the apiserver's
  view of etcd), p99 spikes to 21-25 seconds during the worst incidents, affecting unrelated
  resources simultaneously (rules out resource-specific churn).

- **Ceph HEALTH_OK between incidents.** No persistent cluster health problems. `ceph status` shows
  all mons in quorum, all OSDs up, PGs active+clean.

### Evidence sources

- `./scripts/query-vm.py query 'histogram_quantile(...)'` for apiserver and etcd latency histograms
- `talosctl dmesg` on control plane nodes for `[talos] service[etcd] Health check failed` events
  and `libceph: ... socket closed/error` events
- `kubectl -n rook-ceph logs rook-ceph-operator-...` for `mon "X" out of quorum` messages
- `kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph tell mon.j mon_status` and `perf dump`

## Investigation

### What was ruled out

- **Not silence-operator-specific.** silence-operator uses 17 MiB memory and 2-3 millicores CPU. It
  is not resource-starved. Controller-runtime's leader election has a hardcoded 5-second timeout on
  each lease renewal PATCH; any leader-elected pod in the cluster is vulnerable to the same
  failure mode when the API server is slow.

- **Not resource saturation on any node.** During the worst etcd spike (03:10 UTC on 2026-04-08),
  control plane node disk utilization was 2-5%, CPU was 20-35%, no memory pressure, no OOM events,
  no kernel hung-task or RCU-stall messages. `/proc/loadavg` on hanekawa showed 1.85 on 8 cores.

- **Not control plane taint misconfiguration.** A subagent initially flagged "missing control plane
  taints" as a cause. This was pattern-matching against typical production clusters. This repo is
  intentionally converged: all 5 nodes run user workloads and Ceph OSDs by design. Taints are not
  appropriate for this architecture. See AGENTS.md (should be documented there per follow-up).

- **Not Ceph OSD saturation.** OSD-5 on hanekawa shows `ceph osd perf` commit latency of 9ms,
  RocksDB stall count of 0, no slow ops reported. PostgreSQL workloads (immich-postgres,
  seerr-postgres) on hanekawa do write to Ceph but are not the primary heavy writers. User
  confirmed that Sabnzbd and qBittorrent intermediate I/O (par2 repair, extraction) is redirected
  to NFS on Nezuko, not Ceph, specifically because earlier incidents with ceph-filesystem caused
  service hangs during heavy I/O.

- **Not network interface errors.** `node_network_receive_errs_total` and
  `node_network_transmit_errs_total` show zero errors on all control plane nodes. No NIC resets,
  driver errors, or packet drops in dmesg. Cilium health status is OK on all nodes.

- **Not a mon container crash.** The mon-j pod has 7 restarts, but all terminations are Exit Code
  0 / Reason: Completed (clean shutdowns). The mon container has no livenessProbe, readinessProbe,
  or startupProbe configured. Restarts are driven by Rook operator's "mon out of quorum timeout"
  logic, which recreates the mon pod when quorum isn't restored within the timeout. This is
  reactive remediation by Rook, not a sign that the mon process is intrinsically unstable.

- **Not an etcd data problem.** etcd database sizes are healthy (132/170/178 MB across the 3 CP
  nodes), defrag runs nightly at 02:00 UTC and completes in ~1 minute, Raft index matches across
  all members, no alarms.

### What was observed

**Ceph mon quorum loss incidents (from Rook operator logs, last 120 hours):**

| Timestamp (UTC)              | Mon | Node     | Out of Quorum Duration |
| ---------------------------- | --- | -------- | ---------------------- |
| 2026-04-05 ~05:02-05:03      | j   | hanekawa | ~1 minute              |
| 2026-04-07 14:57:58-14:58:44 | j   | hanekawa | 46 seconds             |
| 2026-04-08 03:08:19-03:09:50 | j   | hanekawa | 1m 31s                 |
| 2026-04-08 14:03:27-14:05:43 | m   | marin    | 2m 16s                 |

Additional etcd-only incidents (etcd slow but no mon quorum loss recorded) occurred on other days.

**dmesg event sequence for 2026-04-08 03:08 UTC incident on hanekawa:**

```txt
03:08:03  [talos] service[etcd](Running): Health check failed: context deadline exceeded
03:08:17  [talos] service[etcd](Running): Health check successful (14s stall)
03:08:19  Rook operator: marking mon "j" out of quorum
03:08:25  libceph: mon2 socket closed (con state OPEN)
03:08:28  libceph: mon1 socket closed (con state OPEN)
03:08:28-40  libceph: mon0 "socket error on write" (9 repeats)
03:08:43  [talos] service[etcd](Running): Health check failed: context deadline exceeded
03:08:46  mon container on hanekawa terminated (exit 0, by Rook)
03:08:48  [talos] service[etcd](Running): Health check successful
03:09:15  mon container restarted
03:09:50  Rook operator: mon "j" is back in quorum
```

**Temporal ordering:** etcd slowness shows up FIRST, THEN Rook detects mon-j out of quorum, THEN
libceph kernel errors appear as RBD clients retry against the failing mon. This suggests the
direction of causation may be "host disturbance affects etcd first, then affects Ceph mon seconds
later" rather than "Ceph mon problems cause etcd slowness." However, Rook's quorum loss detection
is poll-based and lags the actual loss by seconds, so this ordering is not definitive.

**Asymmetry across control plane nodes:**

- hanekawa: 23 etcd health check failures in the current dmesg buffer, 4 mon quorum loss incidents
- marin: 3 etcd health check failures, 1 mon quorum loss incident
- sakura: 0 etcd health check failures, 0 mon quorum loss incidents

sakura is immune so far. Hardware is identical across all three (8 cores, 64Gi RAM, kernel
6.18.18-talos, Samsung 970 EVO Plus 1TB NVMe for Ceph OSD, SATA SSD for Talos system disk).

**hanekawa vs sakura workload differences:**

- hanekawa runs 46 pods including immich + immich-postgres, seerr-postgres, 3 radarr instances, 2
  sonarr instances, qbittorrent, kopia, donetick, 2 envoy gateway pods. Has 16 RBD devices
  attached via krbd.
- sakura runs 25 pods and has 2 RBD devices attached.

Workload difference exists but there is no direct causal link yet to explain why it would manifest
as coincident etcd + Ceph mon disturbance.

### Wrong hypotheses during investigation

Two subagent investigations produced partially hallucinated findings that wasted effort:

1. First subagent recommended "add control plane taints" without understanding the converged
   architecture of this cluster.

2. Second subagent claimed mon-j logs contained "slow ops" and "slow election of 12.8387 seconds"
   messages that do not exist in the actual mon-j logs. Spot-checking the mon-j logs directly
   showed only routine RocksDB compaction activity with zero stalls. The specific log lines were
   fabricated.

Lesson: subagent findings with specific log quotes or numeric values must be spot-checked against
the raw source before acting on them.

### Accidental mutation during investigation

`ceph tell mon.j sync_force --yes-i-really-mean-it` was run while exploring unfamiliar `ceph tell`
commands. This sets a flag that only takes effect on next mon.j restart, causing a full store sync
from another mon. Not damaging, just slower startup when mon.j eventually restarts. Flag status is
visible via `ceph tell mon.j mon_status` (sync_provider field). No immediate action needed.

## Root Cause

**Unknown.** The practical observation is:

1. The Kubernetes API server occasionally becomes slow on writes for 15-120 seconds at a time
2. This is because etcd on the current Raft leader (currently hanekawa) is slow during these
   windows
3. These windows coincide with Ceph mon quorum loss events
4. Leader-elected controllers across the cluster lose their leases during these windows and restart
5. The underlying host-level or network-level disturbance that affects both etcd and ceph-mon
   simultaneously has not been identified

Candidate hypotheses not yet tested:

- Network micro-partitions on the control plane subnet affecting etcd peer traffic and Ceph mon
  Paxos heartbeats simultaneously
- Kernel-level pauses (memory reclaim, softirq storms, IRQ blocking) that stall both etcd fsync
  and ceph-mon processes at once
- Ceph mon Paxos timeouts being too aggressive for this environment (defaults: mon_lease 5s,
  mon_election_timeout 5s, mon_lease_renew_interval_factor 0.6)
- Converged-deployment-specific kernel resource contention that isn't visible in top-level metrics
- Ceph v19.3 regression (installed via `build(deps): update rook ceph ( v1.19.2 ➜ v1.19.3 )`
  recently)

## Resolution

Not resolved. Investigation paused at the point where better diagnostic tooling is needed to make
continued investigation productive. See companion ADR/planning work for diagnostic improvements
being planned:

- Ceph mon debug logging shipped to VictoriaLogs (currently no Ceph logs are shipped at all since
  Vector DaemonSet removal)
- Long-term retention of additional Ceph and etcd metrics
- Hardware-level diagnostics at the Talos layer (SMART, memtest, PCIe/NVMe error counters)
- Unification of logs and metrics behind VictoriaMetrics/VictoriaLogs

Once diagnostic improvements are in place, the next incident window can be captured with enough
evidence to determine whether this is a network, kernel, or Ceph tuning issue.

## Lessons Learned

- **Leader-elected controllers are a cluster-wide health signal.** When many unrelated controllers
  show matching restart counts, look for API server slowness, not per-app bugs.
- **Controller-runtime's 5-second lease timeout is hardcoded.** Any controller using default
  leader election settings will fail under API latency spikes. Some operators expose tuning knobs;
  most do not.
- **Spot-check subagent findings that include specific log quotes or numbers.** Subagent reports
  are faster than manual exploration but susceptible to hallucination. The correct workflow is:
  delegate broad investigation, return with hypotheses and evidence, then verify specific claims
  against primary sources before acting.
- **The absence of log collection is a real limit on investigation.** This cluster intentionally
  disabled centralized log collection (Vector DaemonSet) in November 2025 to reduce Ceph write
  amplification. That decision made sense at the time but leaves gaps for infrastructure
  debugging. Reintroducing targeted log shipping for critical infrastructure components (etcd,
  ceph-mon, kube-controller-manager) may be worth the cost.

## References

- [rook-ceph-volumeattachment-rbac-stuck-2025-10-31.md][rook-rbac]: earlier Rook Ceph issue,
  different failure mode (kubelet volume manager corruption)
- [cilium-bbr-timeout-investigation-2025-11-14.md][cilium-bbr]: earlier 120s timeout pattern on
  pod-to-pod traffic, resolved by disabling BBR; may have left residual tuning worth checking
- [ADR-007: CUBIC over BBR congestion control][adr-007]
- [Kubernetes leader election leases][k8s-leases]
- [controller-runtime leader election options][ctrl-runtime-le]
- [Ceph mon Paxos configuration reference][ceph-mon-config]

[rook-rbac]: /docs/investigations/rook-ceph-volumeattachment-rbac-stuck-2025-10-31.md
[cilium-bbr]: /docs/investigations/cilium-bbr-timeout-investigation-2025-11-14.md
[adr-007]: /docs/decisions/007-cubic-over-bbr-congestion-control.md
[k8s-leases]: https://kubernetes.io/docs/concepts/architecture/leases/
[ctrl-runtime-le]: https://pkg.go.dev/sigs.k8s.io/controller-runtime/pkg/manager#Options
[ceph-mon-config]: https://docs.ceph.com/en/latest/rados/configuration/mon-config-ref/
