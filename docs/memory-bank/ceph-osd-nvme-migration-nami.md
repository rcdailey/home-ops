# Ceph OSD NVMe Migration - Nami Node

**Date**: 2025-10-11
**Last Updated**: 2025-10-11
**Status**: Planning Complete - Awaiting Hardware Delivery

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

**Specifications:**
- CPU: Intel Core i7-8559U (8th gen)
- Storage slots:
  - 1x M.2 22x42/80 (PCIe NVMe or SATA M.2) - **CURRENTLY EMPTY**
  - 2x 2.5" SATA bays - **BOTH OCCUPIED**
- Active cooling: CPU fan provides airflow

**Current Configuration:**
- sda: 500GB MX500 SATA SSD (OS)
- sdb: 2TB BX500 SATA SSD (OSD.1)
- M.2 slot: **EMPTY** ← NEW DRIVE DESTINATION

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

**Post-Migration Setup (3 drives):**
1. M.2 NVMe: 2TB Samsung 990 Pro → **New OSD (OSD.6 or next available)**
2. SATA sda: 500GB MX500 → OS/system
3. SATA sdb: 2TB BX500 → Repurpose (non-critical storage, or remove from Ceph)

**Total Storage:** 4.5TB on nami node

## Migration Plan

### Prerequisites

**Physical Installation:**
1. Power down nami node
2. Install Samsung 990 Pro 2TB in M.2 slot
3. Power up nami node
4. Verify drive detection

**Verification Commands:**
```bash
# Check drive is detected
talosctl -n 192.168.1.50 get disks | rg nvme

# Get device ID (needed for Rook config)
talosctl -n 192.168.1.50 get disks | rg nvme
# Look for: /dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_<SERIAL>
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

#### Phase 1: Add New NVMe OSD (Day 1 - After Hardware Install)

**Step 1: Get Device ID**
```bash
talosctl -n 192.168.1.50 get disks | rg nvme
# Expected output includes:
# nvme0n1   2.0 TB   false   nvme   Samsung_SSD_990_PRO_2TB   <SERIAL>
# Device ID will be: /dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_<SERIAL>
```

**Step 2: Add New OSD to Configuration**

Edit `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml`:

```yaml
storage:
  useAllNodes: false
  useAllDevices: false
  nodes:
  # Keep existing nami entry for BX500
  - name: "nami"
    devicePathFilter: "/dev/disk/by-id/ata-CT2000BX500SSD1_2513E9B2B5A5"
    config:
      deviceClass: "ssd"
      metadataDevice: ""
      osdsPerDevice: "1"
  # ADD NEW: nami-nvme entry
  - name: "nami"
    devicePathFilter: "/dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_<ACTUAL_SERIAL>"
    config:
      deviceClass: "ssd"
      metadataDevice: ""
      osdsPerDevice: "1"
  # ... other nodes unchanged
```

**Step 3: Validate and Apply**
```bash
# Validate configuration
./scripts/flux-local-test.sh
pre-commit run --files kubernetes/apps/rook-ceph/cluster/helmrelease.yaml

# Commit and push
git add kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
git commit -m "feat(rook-ceph): add Samsung 990 Pro NVMe OSD to nami node"
git push

# Monitor OSD creation
kubectl get pods -n rook-ceph -w | rg osd

# Wait for new OSD to appear (will be OSD.6 or next available)
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd tree
```

**Step 4: Monitor Rebalancing**
```bash
# Watch cluster rebalance (automatic)
watch -n 5 "kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status"

# Monitor OSD utilization
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd df tree

# Check PG migration progress
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph pg dump | rg active+clean | wc -l
# Should equal 265 (total PGs) when complete
```

**Expected Timeline:**
- OSD creation: 5-10 minutes
- Initial rebalancing: 30-60 minutes (depends on data)
- Full cluster rebalance: 2-4 hours

**Validation:**
- New OSD appears in `ceph osd tree` as OSD.6 (or next available)
- Cluster status: `HEALTH_OK` after rebalancing
- New OSD receives ~256 PGs (balanced with other OSDs)

#### Phase 2: Remove Old BX500 OSD (Day 2 - After Rebalance Complete)

**Wait Criteria:**
- Cluster status: `HEALTH_OK`
- All PGs: `active+clean`
- Rebalancing complete (check `ceph status` shows no rebalancing)
- At least 24 hours of stable operation

**Step 1: Reduce OSD.1 Weight (Optional - Gradual Migration)**

If you want gradual data migration before removal:
```bash
# Reduce OSD.1 weight to trigger slow rebalancing
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd reweight 1 0.5

# Wait for rebalancing to complete (monitor with ceph status)
# This will migrate ~128 PGs away from OSD.1

# Further reduce if desired
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd reweight 1 0.25
```

**Step 2: Mark OSD.1 Out and Remove**
```bash
# Mark OSD.1 out (triggers data migration)
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd out 1

# Wait for all PGs to migrate off OSD.1 (can take 1-2 hours)
watch -n 5 "kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd df tree | rg 'osd.1'"
# Wait until PGS column shows 0

# Stop OSD.1
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd down 1

# Remove OSD.1 from CRUSH map
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd crush remove osd.1

# Delete OSD.1 authentication
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph auth del osd.1

# Remove OSD.1 from cluster
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd rm 1
```

**Step 3: Update Rook Configuration**

Edit `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml`:

Remove the BX500 entry:
```yaml
# REMOVE THIS ENTIRE BLOCK:
# - name: "nami"
#   devicePathFilter: "/dev/disk/by-id/ata-CT2000BX500SSD1_2513E9B2B5A5"
#   config:
#     deviceClass: "ssd"
#     metadataDevice: ""
#     osdsPerDevice: "1"

# Keep the NVMe entry
- name: "nami"
  devicePathFilter: "/dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_<ACTUAL_SERIAL>"
  config:
    deviceClass: "ssd"
    metadataDevice: ""
    osdsPerDevice: "1"
```

**Step 4: Validate and Apply**
```bash
# Validate configuration
./scripts/flux-local-test.sh
pre-commit run --files kubernetes/apps/rook-ceph/cluster/helmrelease.yaml

# Commit and push
git add kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
git commit -m "feat(rook-ceph): migrate nami OSD from BX500 SATA to 990 Pro NVMe"
git push
```

**Step 5: Physical Cleanup (Optional)**
```bash
# Power down nami
# Remove BX500 drive if no longer needed
# Or repurpose for non-critical storage
```

**Validation:**
- OSD.1 removed from `ceph osd tree`
- Cluster status: `HEALTH_OK`
- 4 OSDs total (was 5 during migration, now 4)
- PG distribution balanced across remaining OSDs

### Rollback Plan

If issues occur during migration:

**During Phase 1 (New OSD Addition):**
```bash
# Remove new OSD immediately if problematic
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd out <new-osd-id>
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd down <new-osd-id>
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd crush remove osd.<new-osd-id>
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph auth del osd.<new-osd-id>
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd rm <new-osd-id>

# Revert Git changes
git revert <commit-hash>
git push
```

**During Phase 2 (Old OSD Removal):**
```bash
# If OSD.1 removal causes issues, add it back
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd in 1
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd up 1

# Restore Git configuration
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

**Immediate (Today):**
- [x] Complete investigation and root cause analysis
- [x] Document findings and migration plan
- [x] Purchase Samsung 990 Pro 2TB from Amazon
- [x] Add temporary anti-affinity rules to reduce nami load

**After Hardware Delivery (Tomorrow):**
- [ ] Power down nami node
- [ ] Install Samsung 990 Pro 2TB in M.2 slot
- [ ] Power up and verify drive detection
- [ ] Execute Phase 1: Add new OSD to cluster
- [ ] Monitor rebalancing (2-4 hours)
- [ ] Validate cluster health and performance

**Day 2-3 (After Stable Operation):**
- [ ] Monitor new OSD performance for 24 hours
- [ ] Execute Phase 2: Remove old BX500 OSD
- [ ] Update configuration to remove BX500 entry
- [ ] Validate final cluster state
- [ ] Confirm `NodeSystemSaturation` alert resolved

**Post-Migration:**
- [ ] Update this document with actual performance metrics
- [ ] Document any issues encountered
- [ ] Consider repurposing BX500 for non-critical storage
- [ ] Monitor cluster performance over 1 week

## Session Resume Context

**When resuming after hardware installation, Claude should:**

1. Verify drive is detected: `talosctl -n 192.168.1.50 get disks | rg nvme`
2. Get exact device ID: `/dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_<SERIAL>`
3. Guide through adding new OSD entry to helmrelease.yaml
4. Monitor OSD creation and rebalancing
5. Provide validation commands
6. Wait for stable operation before OSD.1 removal

**Critical files to review:**
- `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml` - OSD configuration
- This document - Complete migration plan and context

**Expected questions from user:**
- "Drive is installed, what's the device ID?"
- "How do I add it to the cluster?"
- "Is rebalancing complete?"
- "When can I remove the old OSD?"

**Ready to proceed with Phase 1 migration steps.**
