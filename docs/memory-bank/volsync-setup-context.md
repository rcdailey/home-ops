# VolSync Setup Context - 2025-08-05

## Problem Statement

User encountered Flux reconciliation failure:
```
ClusterPolicy/cert-manager/prevent-protected-pvc-deletion dry-run failed:
no matches for kind "ClusterPolicy" in version "kyverno.io/v1"
```

## Root Cause Analysis

- Kyverno ClusterPolicy resource exists in `kubernetes/components/common/pvc-protection-policy.yaml`
- Kyverno is NOT installed in the cluster (no kyverno namespace, no pods)
- ClusterPolicy was included in `kubernetes/components/common/kustomization.yaml`

## Immediate Fix Applied

Removed the ClusterPolicy reference from `kubernetes/components/common/kustomization.yaml:9`:
```yaml
# REMOVED LINE:
# - ./pvc-protection-policy.yaml
```

Status: Fixed - ready for user to commit and push changes.

## User Follow-up Question

User asked about PVC protection during namespace migrations:
- Is `prune: false` annotation enough to prevent PVC deletion during service moves?
- Answer: NO - prune annotation only prevents Flux deletion, not namespace deletion or manual deletion

## VolSync Solution Proposal

User requested VolSync setup for PVC protection and migration capabilities.

### Current Cluster State
- Rook Ceph v1.17.5 with CSI snapshots enabled
- NO CSI snapshot CRDs or controller installed
- NO VolumeSnapshotClasses configured
- NO VolSync installed

### Research Completed
- Latest CSI External-Snapshotter: v8.3.0
- Latest VolSync: v0.13.0
- Rook Ceph snapshot support confirmed: `enableSnapshot: true` in operator config

### Required Installation Sequence
1. Install CSI Snapshot CRDs (3 CRDs needed)
2. Install CSI Snapshot Controller in kube-system
3. Create VolumeSnapshotClasses for Rook Ceph (RBD + CephFS)
4. Install VolSync operator via Helm
5. Configure ReplicationSource policies as needed

### Key Configuration Details

**CSI Snapshot Controller:**
- Image: `registry.k8s.io/sig-storage/snapshot-controller:v8.3.0`
- Deploy in kube-system namespace
- Single replica sufficient for minimal setup

**VolumeSnapshotClasses needed:**
- RBD (block): driver `rook-ceph.rbd.csi.ceph.com`
- CephFS: driver `rook-ceph.cephfs.csi.ceph.com`
- Use existing CSI secrets: `rook-csi-rbd-provisioner` and `rook-csi-cephfs-provisioner`

**VolSync Helm Chart:**
- Repository: `https://backube.github.io/helm-charts/`
- Chart: `backube/volsync`
- Version: `0.13.0`
- Namespace: `volsync-system`

## Next Steps When Resumed

1. User commits/pushes the ClusterPolicy fix
2. **Use app-scout to search for VolSync setup examples**
   - `./scripts/app-scout.sh discover volsync`
   - `./scripts/app-scout.sh discover snapshot-controller`
   - Look for real-world deployment patterns and configurations
3. Create CSI snapshot controller deployment in `kubernetes/system/snapshot-controller/`
4. Create VolumeSnapshotClass resources
5. Create VolSync operator deployment
6. Test with basic snapshot policy
7. Document usage patterns for PVC migration

## File Locations

- Fixed file: `kubernetes/components/common/kustomization.yaml`
- Removed reference: `./pvc-protection-policy.yaml` (file still exists but not referenced)
- New directory needed: `kubernetes/system/snapshot-controller/`
- New directory needed: `kubernetes/system/volsync/`

## User Preferences

- Wants minimal setup to start (just CSI snapshots, no S3 backup yet)
- Follows GitOps workflow - Claude doesn't commit/push
- Uses app-template pattern where possible
- Prefers system components in `kubernetes/system/` namespace structure
