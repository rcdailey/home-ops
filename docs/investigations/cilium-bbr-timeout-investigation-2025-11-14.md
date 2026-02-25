# Cilium BBR Timeout Investigation - Pod Networking Performance

- **Date:** 2025-11-14
- **Status:** RESOLVED (see [ADR-007][adr-007], [ADR-008][adr-008])

## Summary

BBR congestion control caused severe timeout issues affecting both external-to-pod (Plex streaming)
and pod-to-pod (VictoriaMetrics) communication. Root cause: Linux kernel BBR stuck-state bug causing
throughput collapse to 100 Kbit/s, compounded by Cilium Bandwidth Manager enforcement. Resolution:
disabled BBR system-wide, enabled Bandwidth Manager with CUBIC. Attempted netkit + BigTCP deployment
also failed due to socketLB namespace incompatibility and GSO/GRO conflicts with Intel e1000e NIC
patches (NICs later replaced with USB-C r8152 adapters in commit `08065c6`).

[adr-007]: /docs/decisions/007-cubic-over-bbr-congestion-control.md
[adr-008]: /docs/decisions/008-cilium-host-legacy-routing.md

## Timeline

- **2025-11-13 19:13-19:18 CST:** Plex 4K streaming buffer exhaustion, 30s timeouts (initial
  incident)
- **2025-11-13 20:00:** Enabled BBR via Talos sysctls (commit 6fc0793), appeared successful
- **2025-11-13 21:07:** Issues recurred despite BBR verification, nconnect reduced 16→4
- **2025-11-14 08:47 UTC:** Enabled Cilium Bandwidth Manager with BBR (commit 0d0492e)
- **2025-11-14 14:49 UTC:** Cilium pods restarted after BBR enablement
- **2025-11-14 15:09 UTC:** VictoriaMetrics RequestErrorsToAPI alert firing (120s timeouts)
- **2025-11-14 Evening:** Attempted netkit deployment with socketLB + BIG TCP - complete cluster
  failure
- **2025-11-14 Late:** Reverted BBR, enabled Bandwidth Manager without BBR - RESOLVED

## Impact Assessment

### Plex Streaming

**Symptoms:**

- Buffer collapsed 27.9s → 228ms over 20 seconds
- 30-second stalls at random file positions
- Broken pipe errors forcing transcoding
- Complete playback failures

**Environment:**

- Client: Nvidia Shield (192.168.1.105) hardwired Cat6
- Server: Plex on kubernetes node marin (192.168.1.59)
- Storage: NFS from nezuko (192.168.1.58:/mnt/user/media)
- Initial config: nconnect=4, CUBIC, 7.5MB TCP buffers

**Evidence:**

```txt
TCP State on Marin Node:
Connection 192.168.1.59:686  -> 192.168.1.58:2049: cwnd:2 ssthresh:2 (collapsed)
Connection 192.168.1.59:1009 -> 192.168.1.58:2049: cwnd:2 ssthresh:2 (collapsed)
Connection 192.168.1.59:940  -> 192.168.1.58:2049: cwnd:57 ssthresh:52 (idle)
Connection 192.168.1.59:950  -> 192.168.1.58:2049: cwnd:2 ssthresh:2 (collapsed)
```

### VictoriaMetrics

**Symptoms:**

- vmagent→vmsingle writes timing out after 120-121 seconds
- Connection reset by peer from vmsingle
- vmagent retries with exponential backoff (max 65.920s)
- Metrics ingestion delays but no data loss

**Environment:**

- vmagent: 10.42.3.110 on node sakura
- vmsingle: 10.42.1.188 on node nami
- Protocol: promremotewrite to `/api/v1/write`
- Batch size: 54766 bytes observed

**Alert Details:**

```promql
Expression: increase(vm_http_request_errors_total[5m]) > 0
Path: /api/v1/write
Protocol: promremotewrite
```

**Impact:** Low data loss risk (vmagent retries indefinitely), but sustained alert noise and metrics
gaps.

## Root Cause Analysis

### BBR Stuck-State Bug

**Research Evidence:**

Google Groups bbr-dev mailing list discussion documented known failure mode where BBR gets stuck in
low-throughput state (~100 Kbit/s) despite adequate bandwidth. Kernel maintainers acknowledged this
as a Linux BBR implementation issue with no timeline for fix.

**Technical Details:**

- BBR can collapse to 100 Kbit/s throughput under certain packet loss/reordering patterns
- Once stuck, connection remains degraded despite network recovery
- CUBIC recovers from similar conditions through conservative additive increase
- Affects both external→pod (Plex NFS) and pod→pod (VictoriaMetrics) traffic

### Why BBR Failed for Intra-Cluster Traffic

**BBR Design Optimization:**

- Optimized for high-latency WAN links (>50ms RTT)
- Uses model-driven bandwidth probing with 8-round cycle
- Requires sustained high RTT to accurately estimate bottleneck bandwidth
- Model assumes network buffers are bottleneck, not application processing

**Cluster Network Characteristics:**

- Sub-millisecond RTT between pods (<2ms typical)
- Low packet loss rate (<0.001% measured)
- Bandwidth probing cycles complete before meaningful data collection
- BBR model misinterprets low-latency as infinite bandwidth
- Aggressive probing triggers spurious congestion events

**CUBIC Advantages for Low-Latency:**

- Loss-based algorithm well-suited for sub-millisecond RTT
- Faster convergence to optimal window size
- Less sensitive to RTT variations
- Industry standard for datacenter/cluster networking

### Configuration That Triggered Issues

**Talos Sysctls (commit 6fc0793):**

```yaml
net.ipv4.tcp_congestion_control: "bbr"
net.core.default_qdisc: "fq"  # Fair queueing required for BBR
```

**Cilium Bandwidth Manager (commit 0d0492e):**

```yaml
bandwidthManager:
  enabled: true
  bbr: true  # Enforces BBR at pod networking layer
bpf:
  hostLegacyRouting: false  # Enables BPF host routing
```

**Combined Effect:**

- Talos sysctls set node-level BBR default
- Cilium Bandwidth Manager enforced BBR for all pod traffic via BPF
- `bpf.hostLegacyRouting: false` routed traffic through BPF datapath exclusively
- No fallback to CUBIC when BBR degraded

## Attempted Solutions

### Fix Attempt #1: TCP Buffer Increase (16MB) - FAILED

**Changes:**

```yaml
net.core.rmem_max: "16777216"  # 16MB
net.core.wmem_max: "16777216"
net.ipv4.tcp_rmem: "4096 262144 16777216"
net.ipv4.tcp_wmem: "4096 65536 16777216"
```

**Result:** Issue recurred with identical symptoms.

**Why It Failed:** Addressed buffer capacity but not congestion control behavior. CUBIC still
collapsed cwnd to 2 under packet loss, making larger buffers irrelevant.

### Fix Attempt #2: BBR + 64MB Buffers + nconnect=16 - PARTIALLY SUCCESSFUL

**Changes:**

```yaml
# Talos sysctls
net.core.rmem_max: "67108864"  # 64MB
net.core.wmem_max: "67108864"
net.ipv4.tcp_rmem: "4096 262144 67108864"
net.ipv4.tcp_wmem: "4096 65536 67108864"
net.ipv4.tcp_congestion_control: "bbr"
net.ipv4.tcp_fastopen: "3"

# NFS mount
Nconnect=16  # Increased from 4
```

**Initial Verification (2 minutes):**

- BBR adoption: 100% (all 16 NFS connections)
- Congestion window: Stable at cwnd=24-38 (was 2)
- Shield buffer: 19-34 seconds (was 228ms)
- Retransmit rate: <0.001%
- Per-connection bandwidth: 56-84 Mbps

**Issue Recurrence (19 minutes later):**

- Streaming different episode, failed after 763MB transferred
- Buffer collapsed 10s → 0.2s
- BBR verified active with healthy cwnd values
- 30-second timeout pattern persisted

**Why It Failed:** BBR masked TCP-layer symptoms (cwnd collapse) but couldn't fix NFS request
distribution imbalance with nconnect=16. Short verification window didn't capture long-term BBR
stuck-state behavior.

### Fix Attempt #3: nconnect=4 + Industry Best Practices - PARTIAL

**Research:**

- Red Hat KB 6998955: nconnect >4 causes severe degradation with sequential I/O
- NetApp: Recommends nconnect=4 as optimal, max 8
- VMware/Azure: nconnect=4 for file serving workloads
- onedr0p/buroa use nconnect=16 successfully for **mixed workloads** (not applicable to sequential
  streaming)

**Changes:**

```yaml
# NFS mount options
Nconnect=4  # Reduced from 16
Timeo=600
Retrans=2
Hard=True
Proto=tcp
Noatime=True
```

**Kept BBR and 64MB buffers intact.**

**Result:** Improved NFS distribution but BBR issues persisted.

### Fix Attempt #4: Netkit Deployment - FAILED

**Context:** Attempted advanced Cilium features based on reference implementations.

**Configuration:**

```yaml
socketLB:
  enabled: true
  hostNamespaceOnly: true
bpf:
  hostLegacyRouting: false
enableIPv4BIGTCP: true
routingMode: native
```

#### Netkit Failure Details

**Symptoms:**

- Complete cluster failure immediately after Cilium restart
- "operation not permitted" errors on all network operations
- 100% packet loss between nodes
- All pods unschedulable due to network unavailability

**Root Causes:**

1. **socketLB Conflict:** `socketLB.hostNamespaceOnly: true` restricts eBPF socket LB to host
   namespace only. Netkit requires socket LB in pod namespaces for cross-node routing. Configuration
   incompatible with netkit datapath.

2. **BIG TCP GSO/GRO Dependency:** `enableIPv4BIGTCP: true` requires Generic Segmentation Offload
   (GSO) and Generic Receive Offload (GRO) enabled in NIC driver. Intel e1000e driver patches
   (formerly `talos/patches/intel-nuc-e1000e/ethernet-tuning.yaml`, removed in commit `76551a4`
   after NIC replacement) disabled GSO/GRO to work around GPU driver issues. BIG TCP failed on every
   network operation.

3. **MTU Misconception:** Initially assumed BIG TCP required jumbo frames (MTU >1500). Research
   clarified BIG TCP works with standard 1500 MTU but **requires** GSO/GRO offload features. Problem
   was driver configuration, not MTU size.

**Emergency Rollback:**

```bash
# Reverted Cilium to previous working configuration
git revert 0d0492e
flux reconcile helmrelease cilium -n kube-system --force

# Cluster recovered after 5 minutes
```

**Lessons Learned:**

- Advanced features require complete compatibility stack verification
- Reference implementations don't guarantee portability (different hardware/drivers)
- socketLB + BIG TCP + e1000e GSO/GRO workarounds fundamentally incompatible
- Test advanced features in isolated environment first

## Final Resolution

**Diagnosis:** BBR stuck-state bug combined with Cilium enforcement created systemic timeout issues
across both external and intra-cluster traffic. Netkit attempt revealed additional feature
incompatibilities. Solution: Disable BBR entirely, use Bandwidth Manager with CUBIC.

### Configuration Changes

**Talos (`talos/patches/global/machine-sysctls.yaml`):**

```yaml
machine:
  sysctls:
    fs.inotify.max_user_watches: "1048576"
    fs.inotify.max_user_instances: "8192"
    # REMOVED BBR sysctls:
    # net.ipv4.tcp_congestion_control: "bbr"
    # net.core.default_qdisc: "fq"

    # KEPT performance sysctls:
    net.core.rmem_max: "67108864"  # 64MB max receive buffer
    net.core.wmem_max: "67108864"  # 64MB max send buffer
    net.ipv4.tcp_rmem: "4096 262144 67108864"
    net.ipv4.tcp_wmem: "4096 262144 67108864"
    net.ipv4.tcp_fastopen: "3"  # TCP Fast Open (reduces handshake latency)
    net.ipv4.tcp_mtu_probing: "1"  # Path MTU discovery
```

**Cilium (`kubernetes/apps/kube-system/cilium/helmrelease.yaml`):**

```yaml
bandwidthManager:
  enabled: true
  # bbr: false (omitted - defaults to CUBIC with EDT)
bpf:
  hostLegacyRouting: false  # Was set to false here; later reverted to true in BGP migration (691bf49)
```

### Verification

**CUBIC Confirmed:**

```bash
$ talosctl -n 192.168.1.59 read /proc/sys/net/ipv4/tcp_congestion_control
cubic

$ talosctl -n 192.168.1.59 read /proc/sys/net/core/default_qdisc
fq_codel  # Default qdisc, not fq (BBR requirement removed)
```

**Bandwidth Manager Active:**

```bash
$ kubectl exec -n kube-system ds/cilium -c cilium-agent -- cilium status | grep -i bandwidth
Bandwidth Manager:        EDT with BPF [CUBIC] (1500 MTU)
```

**Post-Restart Testing:**

- Plex streaming: 60+ minutes continuous 4K playback, buffer stable 19-34s
- VictoriaMetrics: RequestErrorsToAPI alert cleared, no timeout errors
- No TCP retransmit spikes or connection stalls
- Network metrics healthy across all pods

## Lessons Learned

### Short Verification Windows Misleading

**Problem:** Initial BBR deployment showed perfect metrics for 2 minutes because:

- Fresh mount established 16 connections with even initial distribution
- BBR stuck-state requires sustained load to trigger
- Short verification missed long-term degradation pattern

**Takeaway:** Performance tuning requires sustained testing (30-60 minutes minimum) not spot checks.

### BBR Benefits Don't Apply to All Scenarios

**BBR Optimization:**

- Designed for high-latency WAN links (50-200ms RTT)
- Model-driven bandwidth probing excels with bufferbloat
- Research papers focused on internet congestion scenarios

**Cluster Reality:**

- Sub-millisecond RTT (<2ms typical)
- Negligible bufferbloat (direct L2/L3 paths)
- BBR probing cycles too fast for accurate modeling
- CUBIC loss-based algorithm converges faster

**Industry Practice:** Major cloud providers (AWS, Azure, GCP) use CUBIC for intra-datacenter
traffic, BBR only for WAN/edge acceleration.

**Takeaway:** Algorithm suitability depends on latency profile, not just throughput requirements.

### Advanced Features Interaction Risks

**Netkit Failure Root Cause:**

- socketLB.hostNamespaceOnly incompatible with netkit cross-namespace routing
- BIG TCP requires GSO/GRO enabled, conflicted with e1000e workarounds
- MTU confusion (BIG TCP doesn't need jumbo frames, needs offload features)

**Reference Implementation Trap:**

- onedr0p/buroa repos use netkit successfully with different hardware
- Their NIC drivers support GSO/GRO without GPU driver conflicts
- Direct adoption failed due to environmental differences

**Takeaway:** Advanced features require complete dependency chain validation. Reference
implementations don't guarantee portability across hardware/driver configurations.

### Industry Best Practices vs Reference Implementations

**nconnect Example:**

- Reference repos: nconnect=8-16 for mixed workloads (multiple apps, random+sequential I/O)
- Industry standards: nconnect=4 for sequential streaming (Red Hat, NetApp, VMware, Azure)
- Adopting reference value (16) was incorrect for workload type

**Takeaway:** Vendor recommendations and industry best practices trump reference implementations for
workload-specific tuning. Understand **why** reference configs work for their environment before
adopting.

## Why Advanced Cilium Features Were Skipped

### netkit (Requires 6.8+ kernel)

**Kernel Support:** Talos 6.12 kernel supports netkit.

**Why Skipped:**

- socketLB configuration conflicts with netkit routing requirements
- BIG TCP dependency incompatible with e1000e GSO/GRO workarounds
- Complete cluster failure during attempted deployment
- Risk/benefit analysis: Default routing works reliably

**Future Consideration:** Requires resolving e1000e driver limitations or hardware upgrade to NIC
with working GSO/GRO + GPU drivers.

### BIG TCP (Requires GSO/GRO offload)

**Technical Requirement:** BIG TCP segments packets >64KB using GSO on transmit and GRO on receive.

**Conflict:**

```yaml
# talos/patches/global/machine-ethernet-tuning.yaml
machine:
  network:
    interfaces:
      - interface: enp*
        features:
          - feature: tx-generic-segmentation
            enabled: false  # REQUIRED: GPU driver compatibility
          - feature: rx-gro
            enabled: false  # REQUIRED: GPU driver compatibility
```

**Why Disabled:** Intel e1000e driver with GSO/GRO enabled causes GPU driver initialization
failures. Disabling offload features resolves GPU issues but prevents BIG TCP.

**Tradeoff:** Standard 1500 MTU with 1MB TCP windows provides sufficient throughput for current
workloads (Plex 4K streaming ~80 Mbps). BIG TCP would improve bulk transfers but incompatible with
GPU workloads.

### BBR Congestion Control

**Known Issues:**

- Stuck-state bug causing 100 Kbit/s throughput collapse
- Optimized for WAN (>50ms RTT), not intra-cluster (<2ms RTT)
- CUBIC performs better for low-latency datacenter networking

**Evidence:**

- Plex: 30-second timeouts despite BBR verification
- VictoriaMetrics: 120-second write timeouts
- Both resolved immediately after reverting to CUBIC

**Decision:** CUBIC provides better stability and performance for cluster networking profile.

## References

- [ADR-007: Use CUBIC over BBR for intra-cluster networking][adr-007]
- [ADR-008: Use hybrid BPF routing (hostLegacyRouting: true)][adr-008]
- [Plex timeout investigation][plex-investigation] (separate NFS/GPU issues)
- [Google BBR stuck-state discussion (bbr-dev)][bbr-stuck-state]
- [Cilium Bandwidth Manager documentation][cilium-bwm]
- [Isovalent BBR blog][isovalent-bbr]
- [Red Hat KB 6998955: NFS nconnect performance][redhat-nconnect] (subscription required)

[plex-investigation]: /docs/investigations/plex-timeout-investigation.md
[bbr-stuck-state]: https://groups.google.com/g/bbr-dev/c/XUOKHJiAW80
[cilium-bwm]: https://docs.cilium.io/en/stable/network/kubernetes/bandwidth-manager
[isovalent-bbr]: https://isovalent.com/blog/post/accelerate-network-performance-with-cilium-bbr
[redhat-nconnect]: https://access.redhat.com/solutions/6998955
