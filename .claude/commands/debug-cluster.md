---
allowed-tools: Bash(kubectl get:*), Bash(kubectl describe:*), Bash(kubectl logs:*), Bash(kubectl top:*), Bash(kubectl version:*), Bash(kubectl wait:*), Read, Glob, TodoWrite, Edit, MultiEdit
argument-hint: [namespace/resource] [additional-context]
description: Debug cluster issues using GitOps-compliant investigation and configuration-based solutions
---

# GitOps Cluster Debugging Protocol

## CRITICAL CONSTRAINTS - READ FIRST

!!ABSOLUTE PRIORITY: Configuration-based solutions ONLY!!

- NO kubectl apply, patch, create, delete, or ANY mutating cluster operations
- NO port-forward, exec, or other interactive cluster modifications
- NO reconcile commands - this is STRICTLY read-only investigation
- ALL solutions MUST involve YAML file modifications in this GitOps repository
- ALL research MUST be completed before any planning phase
- MUST use ripgrep (`rg`) instead of `grep`

## Your Investigation Task

Investigate cluster issue: $ARGUMENTS

## Mandatory Investigation Protocol

### 1. INITIAL CLUSTER STATE ANALYSIS

**Start with these kubectl inspection commands (READ-ONLY ONLY):**

```bash
# Get events for the target namespace/resource
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Check resource status
kubectl get <resource-type> -n <namespace> -o wide
kubectl describe <resource> -n <namespace>

# Check pod status and logs if applicable
kubectl get pods -n <namespace> -o wide
kubectl logs <pod-name> -n <namespace> --previous --tail=50
```

### 2. REPOSITORY CONFIGURATION ANALYSIS

**Systematically examine relevant YAML files:**

- Read the application's HelmRelease configuration
- Check Kustomization files and dependencies
- Verify External Secrets and ConfigMaps
- Review PVC and storage configurations
- Examine networking (HTTPRoute, SecurityPolicy)
- Check parent namespace Kustomization structure

### 3. MANDATORY VALIDATION CHECKS

**Common configuration issues to check:**

- Application manifest structure and resource definitions
- Storage configuration and volume mounting
- Networking and service discovery
- Security contexts and permissions
- Resource dependencies and timing

### 4. SOLUTION FORMULATION

**After completing ALL investigation:**

- Identify root cause based on cluster state + configuration analysis
- Formulate YAML-based solution that addresses the issue
- NO cluster mutations - solutions must be Git-commit based
- Reference specific files and line numbers for changes needed

### 5. VALIDATION PLANNING

**Solutions must include validation approach:**

- How to test the fix (via GitOps workflow)
- Required validation commands post-deployment
- Monitoring approach for the solution

## Output Format

1. **Issue Analysis**: Clear description of what you found wrong
2. **Root Cause**: Technical explanation based on investigation
3. **Configuration Solution**: Specific YAML changes needed with file references
4. **Implementation Notes**: Any deployment considerations
5. **Validation Plan**: How to verify the fix works

Remember: This is a Flux GitOps repository. ALL solutions must work through configuration changes
and Git commits, not direct cluster manipulation.
