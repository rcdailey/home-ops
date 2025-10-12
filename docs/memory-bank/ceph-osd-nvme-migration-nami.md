# Ceph OSD NVMe Migration - Nami Node

**Date**: 2025-10-11
**Last Updated**: 2025-10-12
**Status**: Hardware Delivered - Ready for Migration

## Context

Investigation of `NodeSystemSaturation` alert on nami (192.168.1.50) revealed underlying hardware bottleneck causing high I/O load and Ceph performance issues.

## Problem Analysis

### Root Cause Identified

**Hardware Bottleneck**: Crucial BX500 2TB SATA SSD cannot handle sustained Ceph OSD workload.

### Investigation Summary

**Alert Details:**
- Alert: `NodeSystemSaturation`
- Node: nami (192.168.1.50, Intel NUC8i7BEH, i7-8559U, 8 cores)
- Load: 17.89 (1-min), 18.46 (5-min), 17.73 (15-min)
- Load per core: 2.24 (threshold: 2.0)
- Ceph status: `HEALTH_WARN` - OSD.1 experiencing slow BlueStore operations

**I/O Pressure Analysis:**
- I/O wait time: **27,564s** (massive)
- CPU wait time: 1,210s
- Conclusion: I/O bottleneck, not CPU saturation

**Disk Hardware:**
- sda: Crucial MX500 500GB (SATA) - OS/system - **Adequate performance**
- sdb: **Crucial BX500 2TB (SATA) - OSD.1 - BOTTLENECK**

**Weighted I/O Time Comparison:**
```
nami (BX500 2TB):     27,242s - SLOW OPERATIONS WARNING
marin (870 EVO 250GB):  72,241s - NO WARNING (3x more I/O, no issues!)
hanekawa (870 EVO):     13,546s - NO WARNING
sakura (870 EVO):       13,839s - NO WARNING
```

**Why BX500 Fails:**
- DRAM-less SSD (uses HMB - Host Memory Buffer)
- QLC NAND with small SLC cache
- Severe degradation under sustained random writes
- Poor random I/O performance under load
- **Unsuitable for Ceph OSD workloads**

**OSD Distribution:**
- OSD.1 (nami, BX500 2TB): **256 PGs** (highest due to 2x capacity)
- OSD.2 (marin, 870 EVO 250GB): 183 PGs
- OSD.4 (sakura, 870 EVO 250GB): 183 PGs
- OSD.5 (hanekawa, 870 EVO 250GB): 173 PGs

**Workload Pressure on Nami:**
1. Ceph OSD.1 (256 PGs on slow drive)
2. victoria-logs-single (continuous log writes)
3. vmsingle (time-series metrics)
4. qbittorrent (torrent I/O)

### NUC8i7BEH Storage Capabilities

**CORRECTED Specifications** (verified via physical inspection and talosctl):
- CPU: Intel Core i7-8559U (8th gen)
- Storage slots:
  - 1x M.2 22x42/80 (PCIe NVMe or SATA M.2) - **OCCUPIED**
  - 1x 2.5" SATA bay - **OCCUPIED**
- Active cooling: CPU fan provides airflow

**CORRECTED Current Configuration:**
- sda: 500GB MX500 **M.2 SATA** (model: `CT500MX500SSD4`) - OS/system
- sdb: 2TB BX500 **2.5" SATA** (model: `CT2000BX500SSD1`) - OSD.1
- M.2 slot: **OCCUPIED by MX500** (not empty as originally documented)

**Critical Discovery:**
- Original documentation incorrectly stated "2x 2.5" SATA bays"
- Physical inspection revealed: **1x M.2 slot + 1x 2.5" SATA bay**
- MX500 is M.2 SATA drive (not 2.5" SATA as assumed)
- Both interfaces currently occupied, no empty slots available

## Solution: Add NVMe Drive for New OSD

### Hardware Selection

**Chosen Drive: Samsung 990 Pro 2TB (Bare, No Heatsink)**

**Purchase Link:** [Amazon - Samsung 990 Pro 2TB](https://www.amazon.com/dp/B0BHJJ9Y77)
**Price Range:** $133-160 (October 2025)

**Specifications:**
- Interface: PCIe 4.0 x4 NVMe
- Sequential: 7,450 MB/s read / 6,900 MB/s write
- Random: 1,400K read IOPS / 1,550K write IOPS
- DRAM: 2GB LPDDR4 (critical for Ceph metadata)
- Endurance: 1,200 TBW (600 TBW/TB)
- SLC Cache: 226GB dynamic
- Warranty: 5 years
- Form Factor: M.2 2280 (bare drive, no heatsink)

**Why This Drive:**
1. Excellent random I/O (Ceph's primary workload)
2. Large DRAM cache (BlueStore metadata operations)
3. High endurance rating (sustained writes)
4. Proven reliability in enterprise workloads
5. All-time low pricing ($133-160)
6. No heatsink (fits in NUC M.2 slot, passive cooling sufficient)

**Why No Heatsink:**
- NUC8i7BEH has active CPU fan providing airflow
- PCIe 4.0 drives efficient under normal workloads
- Ceph OSD workload (random I/O) generates less heat than sustained sequential writes
- Testing shows 990 Pro doesn't throttle without heatsink in typical case airflow
- Bare drive fits in NUC M.2 slot without clearance issues

**Alternatives Considered:**
- WD Black SN850X 2TB: $119-160, slightly slower random I/O
- Crucial T500 2TB: $150-170, less proven in enterprise

### Final Configuration

**REVISED Post-Migration Setup (2 drives):**
1. M.2 NVMe: 2TB Samsung 990 Pro → **New Ceph OSD**
2. 2.5" SATA: 2TB BX500 → **Talos OS** (reinstalled)

**Critical Design Decision:**
- **990 Pro allocated to Ceph OSD** (not OS) - Correct priority for bottleneck resolution
- **BX500 allocated to OS** (adequate for Talos, poor for Ceph)
- **MX500 M.2 SATA removed** - No longer needed after swap

**Rationale:**
- Talos OS has minimal disk I/O after boot (mostly in-memory operations)
- Talos ephemeral partition writes are light compared to Ceph OSD workload
- 990 Pro's superior random I/O performance directly addresses the BX500 bottleneck
- BX500 adequate for OS/container ephemeral storage (sequential reads, light writes)

**Total Storage:** 4TB on nami node (OS + OSD on separate drives)

## Migration Plan

**IMPORTANT:** This migration follows procedures documented in:
- [Ceph OSD Operations Runbook](../runbooks/ceph-osd-operations.md) - Generic OSD add/remove procedures
- [Talos Node Replacement Runbook](../runbooks/talos-node-replacement.md) - Generic Talos disk replacement

### REVISED Migration Strategy

**Key Changes from Original Plan:**
1. **Cannot add 990 Pro without removing MX500** - M.2 slot occupied
2. **Must reinstall Talos OS on BX500** - OS moving from MX500 to BX500
3. **990 Pro replaces MX500 in M.2 slot** - For Ceph OSD workload
4. **Requires Talos reinstallation** - Using talhelper + `talosctl apply-config --insecure`

### Prerequisites

**Required before migration:**
1. Talos USB installer (bootable USB with Talos ISO)
2. talhelper installed and configured (`talos/talconfig.yaml` exists)
3. Access to `talos/clusterconfig/` generated configs
4. Samsung 990 Pro 2TB NVMe drive

**Verification of current disk models:**
```bash
# Current Talos disk detection
talosctl -e 192.168.1.50 -n 192.168.1.50 get disks

# Output (verified 2025-10-12):
# sda: CT500MX500SSD4 (M.2 SATA, OS)
# sdb: CT2000BX500SSD1 (2.5" SATA, OSD.1)
```

### Current Rook-Ceph Configuration

**File:** `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml`

**Storage Configuration:**
```yaml
storage:
  useAllNodes: false
  useAllDevices: false
  nodes:
  - name: "nami"
    devicePathFilter: "/dev/disk/by-id/ata-CT2000BX500SSD1_2513E9B2B5A5"  # BX500 - OSD.1
    config:
      deviceClass: "ssd"
      metadataDevice: ""
      osdsPerDevice: "1"
  - name: "marin"
    devicePathFilter: "/dev/disk/by-id/nvme-Samsung_SSD_970_EVO_Plus_1TB_S6S1NJ0TB03807K"
    config:
      deviceClass: "ssd"
      metadataDevice: ""
      osdsPerDevice: "1"
  - name: "sakura"
    devicePathFilter: "/dev/disk/by-id/nvme-Samsung_SSD_970_EVO_Plus_1TB_S6S1NS0W223961P"
    config:
      deviceClass: "ssd"
      metadataDevice: ""
      osdsPerDevice: "1"
  - name: "hanekawa"
    devicePathFilter: "/dev/disk/by-id/nvme-Samsung_SSD_970_EVO_Plus_1TB_S6S1NS0W224436E"
    config:
      deviceClass: "ssd"
      metadataDevice: ""
      osdsPerDevice: "1"
```

### Migration Steps

#### Phase 1: Drain and Remove Old OSD (Day 1 - Before Physical Swap)

**Reference:** Follow [Removing an OSD](../runbooks/ceph-osd-operations.md#removing-an-osd) procedure.

**Specific parameters for this migration:**
- OSD to remove: `osd.1`
- Device: BX500 (ata-CT2000BX500SSD1_2513E9B2B5A5)
- Node: nami

**Quick reference commands:**
```bash
# Mark out and wait for drain
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd out 1

# Monitor (wait for PGS = 0)
watch -n 10 "kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd df tree | rg 'osd.1'"

# Verify safe to destroy
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd safe-to-destroy osd.1

# Remove from cluster (follow full procedure in runbook)
```

**Validation:**
- OSD.1 removed from `ceph osd tree`
- Cluster status: `HEALTH_OK`
- 3 OSDs remaining (OSD.2, OSD.4, OSD.5)

#### Phase 2: Physical Hardware Swap and Talos Reinstall (Day 1 - After OSD Drain)

**Reference:** Follow [System Disk Replacement](../runbooks/talos-node-replacement.md#system-disk-replacement) procedure.

**Specific parameters for this migration:**
- Node: nami (192.168.1.50)
- Old disk: MX500 M.2 SATA (CT500MX500SSD4) - being removed
- New system disk: BX500 2.5" SATA (CT2000BX500SSD1)
- Additional disk: 990 Pro M.2 NVMe (replacing MX500 in M.2 slot)

**Physical steps:**
1. Power down nami: `talosctl -n 192.168.1.50 shutdown`
2. Remove MX500 from M.2 slot
3. Install 990 Pro NVMe in M.2 slot
4. Verify BX500 still connected to SATA port
5. Boot from Talos USB installer

**Configuration steps:**
```bash
# Verify disks in installer
talosctl disks --insecure --nodes 192.168.1.50

# Update talconfig.yaml installDiskSelector to CT2000BX500SSD1
# Regenerate configs
task talos:generate-config

# Apply configuration (follow runbook for full procedure)
talosctl apply-config --insecure \
  --nodes 192.168.1.50 \
  --file talos/clusterconfig/home-ops-nami.yaml
```

**Expected timeline:**
- Talos install: 2-5 minutes
- Boot and rejoin: 3-5 minutes
- Total downtime: 10-15 minutes

**Validation:**
- Node status: `Ready`
- 990 Pro NVMe appears in disk list
- BX500 shows as system disk

#### Phase 3: Add 990 Pro as New Ceph OSD (Day 1 - After Talos Reinstall)

**Reference:** Follow [Adding an OSD](../runbooks/ceph-osd-operations.md#adding-an-osd) procedure.

**Specific parameters for this migration:**
- Device: Samsung 990 Pro 2TB NVMe
- Node: nami
- Expected OSD ID: OSD.6 (or next available)

**Quick reference:**
```bash
# Get device ID
talosctl -e 192.168.1.50 -n 192.168.1.50 get disks | rg nvme

# Update helmrelease.yaml with devicePathFilter
# Example: /dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_<SERIAL>

# Validate and commit (follow runbook validation steps)
./scripts/flux-local-test.sh
pre-commit run --files kubernetes/apps/rook-ceph/cluster/helmrelease.yaml

# Monitor OSD creation
kubectl get pods -n rook-ceph -w | rg osd
```

**Expected timeline:**
- OSD creation: 5-10 minutes
- Rebalancing: 2-4 hours

**Validation:**
- New OSD appears in `ceph osd tree`
- Cluster status: `HEALTH_OK`
- 4 OSDs total
- PG distribution balanced

### Rollback Plan

**Phase 1 Rollback (OSD Drain Failure):**
```bash
# If OSD.1 drain fails or causes issues
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd in 1

# Revert Rook config if already committed
git revert <commit-hash>
git push
```

**Phase 2 Rollback (Talos Install Failure):**
- Boot from USB installer again
- Revert `talconfig.yaml` to MX500 model
- Regenerate configs and reapply
- **Last resort:** Swap MX500 back into M.2 slot

**Phase 3 Rollback (New OSD Addition Failure):**
```bash
# Remove problematic OSD
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd out <new-osd-id>
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd down <new-osd-id>
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd crush remove osd.<new-osd-id>
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph auth del osd.<new-osd-id>
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd rm <new-osd-id>

# Revert Rook config
git revert <commit-hash>
git push
```

## Expected Outcomes

### Performance Improvements

**Cluster-Level:**
- Elimination of Ceph `HEALTH_WARN` status
- No more BlueStore slow operation warnings
- Balanced OSD performance across all nodes
- Improved overall cluster I/O throughput

**Node-Level (Nami):**
- Load average reduction from ~18 to <8 (below core count)
- I/O wait time reduction (27,000s → <10,000s expected)
- `NodeSystemSaturation` alert resolution
- Improved responsiveness for all workloads

**Application-Level:**
- Faster victoria-logs-single write performance
- Improved vmsingle query latency
- Better qbittorrent torrent performance
- Reduced pod startup times (faster volume mounts)

### Monitoring Metrics

**Before (Baseline):**
- Load 1-min: 17.89, Load per core: 2.24
- I/O wait: 27,564s
- OSD.1 latency: 2ms (lowest but slow operations)
- Ceph status: `HEALTH_WARN`

**Expected After:**
- Load 1-min: <8, Load per core: <1.0
- I/O wait: <10,000s
- New OSD latency: <1ms (NVMe advantage)
- Ceph status: `HEALTH_OK`

**Monitoring Commands:**
```bash
# Node load
kubectl top node nami
kubectl exec -n observability <node-exporter-pod> -- wget -qO- http://localhost:9100/metrics | rg node_load

# Ceph health
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd perf

# I/O stats
kubectl exec -n observability <node-exporter-pod> -- wget -qO- http://localhost:9100/metrics | rg node_disk_io_time_weighted
```

## Important Notes

### CRITICAL Configuration Details

1. **Rook-Ceph uses explicit device selection**: No automatic provisioning
2. **Device IDs must be exact**: Use `/dev/disk/by-id/` paths (not `/dev/nvme0n1`)
3. **Multiple nodes entries allowed**: Same node can have multiple device entries
4. **Rebalancing is automatic**: Ceph handles PG migration once OSD is added
5. **OSD removal requires data migration**: Wait for `ceph status` to show HEALTH_OK

### Safety Considerations

1. **Maintain 3 replica minimum**: Cluster has 3x replication, safe during migration
2. **No downtime expected**: Adding OSD is non-disruptive
3. **Monitor during rebalancing**: Watch for any errors or warnings
4. **Wait 24h before removal**: Ensure new OSD is stable before removing old
5. **Backup verification**: Ensure volsync backups are current before OSD removal

### Alternative Approaches Considered

**Option A: Replace BX500 with NVMe (Rejected)**
- Requires full OSD removal first
- More downtime risk
- Wastes existing 2TB drive

**Option B: Add NVMe, Keep BX500 as OSD (Rejected)**
- Keeps slow drive in cluster
- Doesn't solve performance issue
- Continues to receive traffic

**Option C: Add NVMe, Repurpose BX500 (SELECTED)**
- Zero downtime
- Utilizes all hardware
- BX500 can serve non-critical workloads
- Best performance and resource utilization

## References

### Investigation Session Details

- **Alert**: NodeSystemSaturation on nami (192.168.1.50)
- **Investigation Date**: 2025-10-11
- **Root Cause**: Crucial BX500 2TB DRAM-less SSD bottleneck
- **I/O Analysis**: 27,564s I/O wait, Ceph BlueStore slow operations
- **Hardware Research**: NUC8i7BEH supports M.2 NVMe (22x42/80)
- **Drive Selection**: Samsung 990 Pro 2TB (best random I/O, DRAM cache)

### Key Findings

1. **BX500 is unsuitable for Ceph**: DRAM-less, QLC NAND, poor sustained writes
2. **OSD.1 has highest load**: 256 PGs (2x capacity = 2x weight)
3. **Samsung 870 EVO handles 3x more I/O**: DRAM cache critical for Ceph
4. **NUC8i7BEH has empty M.2 slot**: Can add NVMe without removing SATA
5. **No heatsink needed**: PCIe 4.0 + NUC airflow + Ceph workload = adequate cooling

### Technical Documentation

- [Crucial BX500 Limitations](https://www.tomshardware.com/reviews/crucial-bx500-ssd-review) - DRAM-less, poor sustained writes
- [Samsung 990 Pro Review](https://www.tomshardware.com/reviews/samsung-990-pro-ssd-review) - Excellent random I/O
- [NUC8i7BEH Specs](https://nucblog.net/2018/11/coffee-lake-i7-nuc-review-nuc8i7beh/) - M.2 + 2x SATA simultaneous
- [Rook-Ceph OSD Management](https://rook.io/docs/rook/latest-release/Storage-Configuration/ceph-osd-mgmt/) - Official docs

## Temporary Workload Migration (Pre-NVMe Installation)

**Date Applied:** 2025-10-11
**Status:** Active until Phase 2 completion

To reduce I/O pressure on nami's failing BX500 drive while waiting for NVMe delivery, temporary node anti-affinity rules have been added to prevent heavy I/O workloads from scheduling on nami.

### Applied Anti-Affinity Rules

**1. qbittorrent** (`kubernetes/apps/media/qbittorrent/helmrelease.yaml`):
```yaml
defaultPodOptions:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: kubernetes.io/hostname
            operator: NotIn
            values: [nami]
```

**2. victoria-logs-single** (`kubernetes/apps/observability/victoria-logs-single/helmrelease.yaml`):
```yaml
server:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: kubernetes.io/hostname
            operator: NotIn
            values: [nami]
```

**3. vmsingle** (`kubernetes/apps/observability/victoria-metrics-k8s-stack/helmrelease.yaml`):
```yaml
vmsingle:
  spec:
    affinity:
      nodeAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          nodeSelectorTerms:
          - matchExpressions:
            - key: kubernetes.io/hostname
              operator: NotIn
              values: [nami]
```

### Removal Procedure (After Phase 2 Completion)

**CRITICAL: These anti-affinity rules MUST be removed after the BX500 OSD is successfully removed and the cluster is stable with the new NVMe OSD.**

**When to Remove:**
1. Phase 2 is complete (old OSD.1 removed from cluster)
2. Cluster status is `HEALTH_OK` for 24+ hours
3. New NVMe OSD is handling traffic without issues

**How to Remove:**
1. Remove the entire `affinity:` block from each helmrelease file:
   - `kubernetes/apps/media/qbittorrent/helmrelease.yaml`
   - `kubernetes/apps/observability/victoria-logs-single/helmrelease.yaml`
   - `kubernetes/apps/observability/victoria-metrics-k8s-stack/helmrelease.yaml`
2. Validate: `./scripts/flux-local-test.sh && pre-commit run --files <files>`
3. Commit: `git commit -m "feat: remove nami anti-affinity after NVMe OSD migration complete"`
4. Push and monitor pod rescheduling

**Validation After Removal:**
```bash
# Verify pods can schedule on nami again
kubectl get pods -A -o wide | rg nami

# Check load is balanced
kubectl top node nami

# Verify Ceph health
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status
```

**Expected Outcome:**
- Workloads can schedule on nami again
- Load distributed across all nodes including nami
- NVMe OSD handles I/O efficiently without saturation

## Next Steps

**Completed (2025-10-11):**
- [x] Complete investigation and root cause analysis
- [x] Document findings and migration plan
- [x] Purchase Samsung 990 Pro 2TB from Amazon
- [x] Add temporary anti-affinity rules to reduce nami load

**Hardware Delivered (2025-10-12):**
- [x] Samsung 990 Pro 2TB received
- [x] Physical inspection revealed hardware configuration correction
- [x] Updated migration plan for Talos reinstallation requirement

**Ready to Execute (Phase 1 - Ceph Drain):**
- [ ] Mark OSD.1 out and wait for data migration (1-2 hours)
- [ ] Verify OSD.1 safe to destroy
- [ ] Remove OSD.1 from cluster
- [ ] Update Rook helmrelease.yaml to remove BX500 entry
- [ ] Validate cluster healthy with 3 OSDs

**Phase 2 - Hardware Swap and Talos Reinstall:**
- [ ] Power down nami node
- [ ] Physical swap: Remove MX500 M.2, install 990 Pro M.2
- [ ] Boot from Talos USB installer
- [ ] Verify disk detection and note exact model strings
- [ ] Update `talos/talconfig.yaml` with BX500 model
- [ ] Regenerate Talos configs with `task talos:generate-config`
- [ ] Apply config with `talosctl apply-config --insecure`
- [ ] Verify node rejoins cluster and 990 Pro detected

**Phase 3 - Add New Ceph OSD:**
- [ ] Get 990 Pro device ID from `talosctl get disks`
- [ ] Update Rook helmrelease.yaml to add 990 Pro entry
- [ ] Monitor OSD creation and rebalancing (2-4 hours)
- [ ] Validate cluster health with 4 OSDs
- [ ] Confirm `NodeSystemSaturation` alert resolved

**Post-Migration:**
- [ ] Remove temporary workload anti-affinity rules from helmreleases
- [ ] Monitor cluster performance for 1 week
- [ ] Update this document with actual performance metrics
- [ ] Document any issues encountered

## Session Resume Context

**Critical Discoveries (2025-10-12):**
1. **Hardware configuration corrected**: NUC8i7BEH has 1x M.2 + 1x SATA (not 2x SATA)
2. **M.2 slot occupied**: MX500 M.2 SATA currently installed (not empty as assumed)
3. **Migration requires Talos reinstall**: OS must move from MX500 to BX500
4. **talhelper configured**: Can regenerate configs with `task talos:generate-config`

**Disk Models (verified via talosctl):**
- MX500 M.2 SATA: `CT500MX500SSD4` (will be removed)
- BX500 2.5" SATA: `CT2000BX500SSD1` (will become OS drive)
- 990 Pro NVMe: Model TBD after installation

**Migration Phases:**
1. **Ceph Drain** (1-2 hours) - Remove OSD.1 from cluster
2. **Hardware Swap + Talos Reinstall** (15 minutes downtime) - Physical swap, reinstall OS
3. **Add New OSD** (2-4 hours rebalance) - Add 990 Pro to Ceph

**Critical files to modify:**
- `talos/talconfig.yaml` - Update installDiskSelector to BX500 model
- `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml` - Remove BX500, add 990 Pro

**Talos Reinstall Research:**
- Verified `talosctl apply-config --insecure` is correct method
- Must boot from USB installer first
- Config preserves node identity (IP, hostname, certs)
- Install takes 2-5 minutes

**Ready to begin Phase 1 (Ceph OSD drain).**
