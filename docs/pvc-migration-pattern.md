# Safe PVC Migration Pattern for GitOps

## Overview
This document outlines the safe procedure for migrating applications with persistent storage between Kubernetes namespaces using GitOps workflows, preventing data loss.

## Protection Layers Implemented

1. **Automatic Protection**: Kustomize transformer adds `kustomize.toolkit.fluxcd.io/prune: disabled` to ALL PVCs
2. **Admission Control**: Kyverno policy prevents deletion of protected PVCs
3. **GitOps Workflow**: Structured migration process with validation steps

## Safe Migration Procedure

### Phase 1: Preparation
1. **Verify Current PVC Status**:
   ```bash
   kubectl get pvc -n <source-namespace> <pvc-name> -o yaml
   ```

2. **Create Migration Job Template**:
   ```yaml
   apiVersion: batch/v1
   kind: Job
   metadata:
     name: pvc-migration-<app-name>
     namespace: migration-jobs
   spec:
     template:
       spec:
         containers:
         - name: migrate
           image: alpine:latest
           command: ["/bin/sh", "-c"]
           args:
           - |
             echo "Starting migration..."
             cp -rv /source/* /dest/ || true
             echo "Verifying data integrity..."
             diff -r /source /dest
             echo "Migration complete"
           volumeMounts:
           - name: source-vol
             mountPath: /source
             readOnly: true
           - name: dest-vol
             mountPath: /dest
         volumes:
         - name: source-vol
           persistentVolumeClaim:
             claimName: <source-pvc>
         - name: dest-vol
           persistentVolumeClaim:
             claimName: <dest-pvc>
         restartPolicy: Never
   ```

### Phase 2: Migration Execution
1. **Create destination PVC** (automatically protected):
   ```yaml
   apiVersion: v1
   kind: PersistentVolumeClaim
   metadata:
     name: <app-name>-data
     namespace: <dest-namespace>
     # Automatic protection annotation added by transformer
   spec:
     accessModes: [ReadWriteOnce]
     resources:
       requests:
         storage: <size>
     storageClassName: ceph-block
   ```

2. **Execute migration job**
3. **Verify data integrity**
4. **Deploy application to new namespace**
5. **Test application functionality**

### Phase 3: Cleanup (Only After Verification)
1. **Remove protection annotation from source PVC**:
   ```bash
   kubectl annotate pvc <source-pvc> -n <source-namespace> \
     kustomize.toolkit.fluxcd.io/prune-
   ```

2. **Update GitOps to remove source resources**
3. **Flux will clean up source PVC on next reconciliation**

## Emergency Recovery
If data is accidentally lost:
1. Check for Rook Ceph snapshots
2. Review backup systems
3. Restore from external backups
4. Consider PV recovery procedures

## Validation Commands
```bash
# Check protection status
kubectl get pvc --all-namespaces \
  -o jsonpath='{range .items[*]}{.metadata.namespace}{" "}{.metadata.name}{" "}{.metadata.annotations.kustomize\.toolkit\.fluxcd\.io/prune}{"\n"}{end}'

# Verify Kyverno policy is active
kubectl get cpol prevent-protected-pvc-deletion

# Test protection (should fail)
kubectl delete pvc <protected-pvc> -n <namespace>
```

## Best Practices
- Always test migrations in staging first
- Use separate Kustomizations for storage resources when needed
- Implement monitoring for PVC deletion events
- Regular backup validation procedures
- Document recovery procedures specific to your applications
