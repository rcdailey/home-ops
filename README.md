# Home Operations

Personal Kubernetes homelab managed with Talos Linux and Flux GitOps.

## Stack

- **OS**: Talos Linux
- **GitOps**: Flux
- **Storage**: Rook Ceph
- **Secrets**: External Secrets + Infisical
- **Networking**: Cilium, Envoy Gateway
- **Observability**: VictoriaMetrics + Logs, Grafana
- **Databases**: CloudNativePG
- **Backups**: Volsync, Kopia

## Repository Structure

```txt
bootstrap/          # Cluster bootstrap scripts
docs/
  architecture/     # System design docs
  decisions/        # ADRs
  runbooks/         # Operational procedures
  troubleshooting/  # Historical investigations
kubernetes/
  apps/             # Application manifests by namespace
  components/       # Reusable Kustomize components
  flux/             # Flux system configuration
scripts/            # Operational scripts
talos/              # Talos node configuration
```

## New Machine Setup

Prerequisites: [mise](https://mise.jdx.dev/installing-mise.html) installed.

1. Install minijinja-cli (not managed by mise):

   ```bash
   brew install minijinja-cli
   ```

1. Install remaining tools:

   ```bash
   mise trust && mise install
   ```

1. Authenticate with Infisical:

   ```bash
   infisical login
   ```

1. Generate Talos configuration:

   ```bash
   just talos init-config
   ```

1. Verify access:

   ```bash
   talosctl -n 192.168.1.63 version
   kubectl get nodes
   ```

## Disaster Recovery

Bootstrap a new cluster from scratch:

1. Bootstrap Talos cluster:

   ```bash
   just bootstrap talos
   ```

1. Bootstrap applications:

   ```bash
   just bootstrap apps
   ```
