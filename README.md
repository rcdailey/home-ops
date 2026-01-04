# Home Operations

Personal Kubernetes homelab managed with Talos Linux and Flux GitOps.

## New Machine Setup

Prerequisites: [mise](https://mise.jdx.dev/installing-mise.html) installed.

1. Install tools:

   ```bash
   mise trust && mise upgrade
   ```

1. Retrieve age key (required for SOPS decryption):

   ```bash
   rbw get home-ops-age-key > age.key
   ```

1. Generate Talos configuration:

   ```bash
   task talos:generate-config
   ```

1. Fetch kubeconfig from cluster (use any control plane node IP):

   ```bash
   talosctl kubeconfig --force -n 192.168.1.63
   ```

1. Verify access:

   ```bash
   kubectl get nodes
   ```

## Disaster Recovery

Bootstrap a new cluster from scratch:

1. Bootstrap Talos cluster:

   ```bash
   task bootstrap:talos
   ```

1. Bootstrap applications:

   ```bash
   task bootstrap:apps
   ```

## Quick Reference

List available tasks:

```bash
task --list
```

Sync cluster with Git:

```bash
task reconcile
```

Flux resource status:

```bash
flux get all -A
```
