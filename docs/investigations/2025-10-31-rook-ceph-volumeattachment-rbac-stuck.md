# Rook-Ceph VolumeAttachment RBAC Loop

- **Date:** 2025-10-31
- **Status:** RESOLVED

## Summary

Plex pod stuck in ContainerCreating for 4+ hours due to kubelet volume state machine corruption
triggered by Node Authorizer RBAC failures during VolumeAttachment verification. Kubelet repeatedly
enters MountVolume.WaitForAttach, succeeds verification, but loops back instead of proceeding to
NodeStageVolume/NodePublishVolume operations.

**Resolution**: Restart kubelet service on affected node to reset volume manager state.

## Symptoms

- Pod stuck in ContainerCreating indefinitely (4+ hours)
- VolumeAttachments show `attached: true`
- No CSI NodeStageVolume/NodePublishVolume activity in CSI nodeplugin logs
- Kubelet logs show repeating pattern:

  ```txt
  MountVolume.WaitForAttach entering for volume
  MountVolume.WaitForAttach failed: User "system:node:lucy" cannot get resource "volumeattachments" ... no relationship found
  MountVolume.WaitForAttach succeeded for volume
  [loops back to WaitForAttach instead of proceeding to mount]
  ```

- Pod conditions: `PodReadyToStartContainers: False` with empty reason/message
- Error: `unmounted volumes=[config config-cache vector-data], unattached volumes=[], failed to
  process volumes=[]: context deadline exceeded`

## Root Cause

Kubernetes issue [#120571](https://github.com/kubernetes/kubernetes/issues/120571): Volume state
machine corruption when:

1. Node Authorizer RBAC denies kubelet access to VolumeAttachments during WaitForAttach phase
2. Error message: `no relationship found between node 'X' and this object`
3. Kubelet retries with exponential backoff (2m2s intervals)
4. WaitForAttach eventually succeeds as VolumeAttachment stabilizes
5. **Bug**: Kubelet internal state corrupted by early RBAC failures, loops back to WaitForAttach
   instead of progressing to mount phase
6. CSI nodeplugin never receives NodeStageVolume/NodePublishVolume calls
7. Pod remains stuck even though volumes are attached and healthy

## Environment

- Talos Linux: 1.11.3
- Kubernetes: 1.31.x
- Rook-Ceph: 1.18.4
- Storage: RWO volumes on ceph-block storage class

## Key Findings

### RBAC Configuration is Normal

`system:node` ClusterRoleBinding having empty subjects is **expected behavior** in Kubernetes. Node
authorization happens via Node Authorizer (certificate-based), not RBAC subjects. Verified with
onedr0p's cluster showing identical empty subjects configuration.

### VolumeAttachment Lifecycle

1. **Attach phase** (CSI controller): Creates VolumeAttachment resource, executes `rbd map`, sets
   `status.attached: true`
2. **Stage phase** (CSI nodeplugin): Kubelet calls NodeStageVolume to format and mount to staging
   path
3. **Publish phase** (CSI nodeplugin): Kubelet calls NodePublishVolume to bind mount into pod's
   volume path
4. **Container start**: Containers launched with volumes available

**Stuck point**: Between attach and stage. Kubelet never calls CSI nodeplugin for
staging/publishing.

### Why Other Pods Work

15 pods with RWO volumes ran successfully on lucy during the incident. The RBAC error is transient
during VolumeAttachment creation/verification. Healthy pods complete WaitForAttach verification
before RBAC timing issues occur. Plex pod hit the specific timing window where early RBAC denials
corrupted kubelet's volume manager state machine for this specific pod UID.

### Why Pod Deletion Didn't Help Initially

Early pod deletions occurred while volumes were still attached to original node (hanekawa). New pod
scheduled to different node (lucy) created new VolumeAttachments while old ones still existed,
triggering Multi-Attach errors and RBAC relationship failures. Once old VolumeAttachments were
manually deleted, pod deletion still didn't work because kubelet volume manager state persists in
memory across pod lifecycles for the same PVC.

## Investigation Steps

### Diagnosis Commands

```bash
# Check pod status and conditions
kubectl get pod -n <namespace> <pod-name>
kubectl describe pod -n <namespace> <pod-name>
kubectl get pod -n <namespace> <pod-name> -o jsonpath='{.status.conditions[*]}'

# Check VolumeAttachments
kubectl get volumeattachment -o wide
kubectl get volumeattachment -o yaml | grep -A 20 <pvc-name>

# Check kubelet logs for volume operations (Talos)
talosctl -n <node-ip> logs kubelet | rg "MountVolume.WaitForAttach|NodeStage|NodePublish"

# Check CSI nodeplugin activity
kubectl logs -n rook-ceph <csi-rbdplugin-pod> -c csi-rbdplugin --tail=200

# Check CSI staging paths
talosctl -n <node-ip> ls /var/lib/kubelet/plugins/kubernetes.io/csi/rook-ceph.rbd.csi.ceph.com/

# Check volume mounts on node
talosctl -n <node-ip> read /proc/mounts | grep <pvc-uuid>

# Check Ceph RBD mappings
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd showmapped

# Check RBD image status
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd status ceph-blockpool/<image-name>
```

### Key Log Patterns

**Kubelet stuck in WaitForAttach loop**:

```txt
MountVolume.WaitForAttach entering for volume "pvc-xxxxx"
Operation failed. No retries permitted until <timestamp> (durationBeforeRetry 2m2s)
Error: ... cannot get resource "volumeattachments" ... no relationship found
MountVolume.WaitForAttach succeeded for volume "pvc-xxxxx"
[repeats indefinitely without progressing to NodeStageVolume]
```

**No CSI nodeplugin activity**:

```bash
# Empty result indicates kubelet never called CSI driver
kubectl logs -n rook-ceph <nodeplugin> | grep "NodeStageVolume\|NodePublishVolume"
```

## Resolution

### Immediate Fix

Restart kubelet on affected node to reset volume manager state:

```bash
# Talos Linux
talosctl -n <node-ip> service kubelet restart

# Standard Kubernetes (if accessible)
systemctl restart kubelet
```

After restart:

- Kubelet volume manager resets internal state
- New pod attempts proceed through normal attach → stage → publish flow
- Volumes mount successfully

### Important Note

After kubelet restart, pod may transition from ContainerCreating to CrashLoopBackOff if volumes have
stale file handles or corruption. This is normal - delete the pod to allow clean recreation with
fresh mounts.

## Preventive Measures

### Monitor for Early Warning Signs

```bash
# Alert on pods stuck in ContainerCreating > 5 minutes
kubectl get pods -A --field-selector status.phase=Pending -o json | \
  jq '.items[] | select(.status.conditions[] |
    select(.type=="PodReadyToStartContainers" and .status=="False"))'

# Check for VolumeAttachment RBAC errors
talosctl -n <node-ip> logs kubelet | \
  rg "cannot get resource \"volumeattachments\"" | tail -10
```

### Kubernetes Configuration

Ensure Node Authorizer is properly configured in kube-apiserver (Talos handles this automatically):

```yaml
# Verify via kube-apiserver flags
--authorization-mode=Node,RBAC
```

### Avoid Triggering Conditions

Based on [K8s issue #120571](https://github.com/kubernetes/kubernetes/issues/120571), this occurs
when:

1. Volume detach fails with transient error (timeout)
2. kube-controller-manager restarts during volume operations
3. New pod scheduled using same volume before previous detach completes

**Mitigation**: Avoid restarting kube-controller-manager during active volume operations. On Talos,
this is managed by the control plane lifecycle.

## Related Issues

- Kubernetes issue [#120571](https://github.com/kubernetes/kubernetes/issues/120571): Pods stuck
  ContainerCreating after volume detach error and KCM restart
- Kubernetes issue [#69158](https://github.com/kubernetes/kubernetes/issues/69158): Kubelet stuck in
  WaitForAttach when AttachVolume.Attach failed
- Kubernetes issue [#116847](https://github.com/kubernetes/kubernetes/issues/116847):
  UnmountVolume.NewUnmounter failed after volume operations

## Additional Context

### system:node ClusterRoleBinding

The empty subjects in `system:node` ClusterRoleBinding is **not** the root cause. This is standard
Kubernetes configuration where Node Authorizer handles authorization based on node client
certificates, not RBAC subject bindings.

```yaml
# Normal configuration
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: system:node
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:node
subjects: []  # Empty is expected with Node Authorizer
```

### VolumeAttachment Orphaning

When terminating pod with RWO volumes is stuck (>5min), manually clean up VolumeAttachments:

```bash
# Identify VolumeAttachments for specific PVCs
kubectl get volumeattachment -o json | \
  python3 -c "import json,sys; va=json.load(sys.stdin); \
  [print(v['metadata']['name']) for v in va['items'] \
  if 'pvc-xxxxx' in v['spec']['source']['persistentVolumeName']]"

# Delete orphaned VolumeAttachments
kubectl delete volumeattachment <attachment-name>
```

However, this alone won't fix the stuck pod - kubelet restart is still required.

## Timeline

- **14:15 UTC**: Plex pod entered ContainerCreating after previous pod termination
- **14:15-18:30 UTC**: Pod stuck with WaitForAttach loops, RBAC errors every 2m2s on lucy
- **18:30 UTC**: Diagnosis revealed kubelet never progressed past WaitForAttach despite success
  messages
- **18:38 UTC**: Kubelet restarted on lucy, pod transitioned to CrashLoopBackOff (progress)
- **18:40 UTC**: Pod deleted, new pod created and scheduled to hanekawa
- **18:40-18:45 UTC**: New pod stuck in ContainerCreating on hanekawa with same symptoms
- **18:45 UTC**: Kubelet restarted on hanekawa
- **18:46 UTC**: Pod successfully started (Running 2/2)
- **Resolution**: Kubelet restart required on **both** affected nodes, confirming cluster-wide
  kubelet volume manager issue, not node-specific configuration problem

## References

- [Rook-Ceph CSI common issues][rook-csi]
- [Kubernetes volume lifecycle documentation][k8s-volumes]
- [Kubernetes issue #120571][k8s-120571]: Volume state machine corruption after detach error

[rook-csi]:
    https://github.com/rook/rook/blob/master/Documentation/Troubleshooting/ceph-csi-common-issues.md
[k8s-volumes]: https://kubernetes.io/docs/concepts/storage/persistent-volumes/
[k8s-120571]: https://github.com/kubernetes/kubernetes/issues/120571
