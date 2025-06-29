# Session: Talos Kubernetes Cluster Setup

## Status

- **Phase**: Complete
- **Progress**: All README requirements completed

## Objective

Deploy a 3-node Talos Kubernetes cluster with Flux GitOps, following the cluster-template README workflow. Migrate from existing docker-compose setup on Nezuko to Kubernetes while maintaining external access through Cloudflare tunnel.

## Current Focus

README workflow completed successfully. Talos Kubernetes cluster fully operational with Flux GitOps, external access, and GitHub webhook integration. Ready for service migration planning.

## Task Checklist

### Phase 1: Machine Preparation ✅
- [x] Download Talos ISO from factory.talos.dev (schematic: 376567988ad370138ad8b2698212367b8edcb69b5fd68c80be1f2ec7d603b4ba)
- [x] Verify nodes available on network (nami: 192.168.1.50, marin: 192.168.1.59, rias VM: 192.168.1.61)

### Phase 2: Local Workstation ✅  
- [x] Install mise CLI and tools (brew install mise)
- [x] Install required CLI tools (task, talosctl, kubectl, helm, flux, etc.)
- [x] Logout of GHCR registries

### Phase 3: Cloudflare Configuration ✅
- [x] Create Cloudflare API token with Zone:DNS:Edit and Account:Cloudflare Tunnel:Read permissions
- [x] Create Cloudflare tunnel "kubernetes" (ID: 6b689c5b-81a9-468e-9019-5892b3390500)

### Phase 4: Cluster Configuration ✅
- [x] Run `task init` to generate config files
- [x] Configure cluster.yaml with network settings (192.168.1.0/24, gateway IPs 70-73)
- [x] Configure nodes.yaml with all 3 nodes (rias, nami, marin) as controllers
- [x] Update age.key to match Bitwarden stored key
- [x] Run `task configure` to generate all Talos/K8s manifests
- [x] Commit initial configuration to git

### Phase 5: Bootstrap Talos, Kubernetes, and Flux ✅
- [x] Boot nami and marin from Talos ISO using USB/KVM
- [x] Run `task bootstrap:talos` to install Talos on all nodes  
- [x] Push talhelper encrypted secret to git
- [x] Run `task bootstrap:apps` to install cilium, flux, etc.
- [x] Watch cluster rollout with `kubectl get pods --all-namespaces --watch`

### Phase 6: Post-Installation Verification ✅
- [x] Check Cilium status: `cilium status` - All networking healthy (3/3 nodes)
- [x] Verify Flux: `flux check`, `flux get sources git flux-system` - All controllers operational, 16 Kustomizations applied
- [x] Test connectivity to gateways (192.168.1.72, 192.168.1.73) - Both responding on port 443
- [x] Verify DNS resolution for echo.<domain> - Resolves to 192.168.1.73 via k8s_gateway
- [x] Check wildcard certificate status - *.<domain> cert issued and ready
- [x] Configure GitHub webhook for flux-webhook.<domain>

### Phase 7: README Cleanup ✅
- [x] Run `task template:tidy` to clean up template files

### Phase 7: Migration Strategy Planning
- [ ] Plan gradual migration from SWAG/Nginx on Nezuko
- [ ] Test K8s services with internal gateway first
- [ ] Migrate services one by one to K8s
- [ ] Update DNS records gradually  
- [ ] Eventually decommission SWAG

### Phase 8: Additional Setup
- [ ] Set up encrypted SOPS versions of config files for cross-machine sync
- [ ] Configure repository cleanup (`task template:tidy`)
- [ ] Enable Renovate for dependency management
- [ ] Set up monitoring and additional applications

## Next Steps

1. Plan service migrations from existing SWAG/Docker setup
2. Test new services using internal gateway before making public
3. Gradually migrate services to Kubernetes cluster
4. Eventually decommission legacy SWAG infrastructure

## Resources

### Network Configuration
- **Network**: 192.168.1.0/24
- **Gateway**: 192.168.1.1  
- **Cluster API**: 192.168.1.70
- **DNS Gateway**: 192.168.1.71
- **Internal Gateway**: 192.168.1.72
- **External Gateway**: 192.168.1.73

### Node Details
| Node | IP | Hardware | Disk | MAC Address | Status |
|------|----|-----------|----|-------------|---------|
| rias | 192.168.1.61 | VM on lucy/Proxmox | /dev/sda | bc:24:11:a7:98:2d | Talos Installed ✅ |
| nami | 192.168.1.50 | Intel NUC | /dev/sda | 94:c6:91:a1:e5:e8 | Talos Installed ✅ |
| marin | 192.168.1.59 | Intel NUC | /dev/nvme0n1 | 1c:69:7a:0d:8d:99 | Talos Installed ✅ |

### Key Files (Not in Git)
- `cluster.yaml` - Contains Cloudflare token, network config
- `nodes.yaml` - Contains MAC addresses, node details  
- `cloudflare-tunnel.json` - Tunnel credentials
- `age.key` - SOPS encryption key (matches Bitwarden)

### Cloudflare Setup
- **Domain**: <domain>
- **Tunnel ID**: 6b689c5b-81a9-468e-9019-5892b3390500
- **API Token**: XoxZ5_WPxLRG29GHFJROXYTR7nP2WZzE4GzCRojM

### Current Migration Context
- **Existing setup**: SWAG reverse proxy on Nezuko (192.168.1.58)
- **Current DNS**: *.<domain> → WAN IP → UDMP → Nezuko:443
- **Goal**: Gradual migration to K8s with parallel operation during transition

## Progress & Context Log

### 2025-06-29 - Session Created

Created session to set up Talos Kubernetes cluster following cluster-template README. 
Initial focus: Complete 5-stage deployment process.
Objectives: Deploy 3-node HA cluster, integrate Cloudflare, plan migration from docker-compose.

### 2025-06-29 - Configuration Phase Complete

Successfully completed Stages 1-4 of README workflow:
- Installed all required tools via mise
- Configured Cloudflare API token and tunnel
- Generated cluster.yaml and nodes.yaml with proper network settings
- Fixed age key mismatch with Bitwarden stored key
- Generated all Talos and Kubernetes manifests 
- Committed initial configuration to git

Key decisions: All 3 nodes configured as controllers for HA. Used existing age key from Bitwarden.
Tunnel created successfully with proper credentials.

### 2025-06-29 - Talos Bootstrap Complete

Successfully completed Talos installation on all 3 nodes:
- Reset cluster to clean maintenance mode using `task talos:reset` 
- Resolved certificate errors by ensuring nodes were properly in maintenance mode
- Bootstrap process generated configuration for all nodes (rias, nami, marin)
- Talos cluster initialized with 3-node HA control plane
- Generated kubeconfig and talosconfig files

### 2025-06-29 - Kubernetes Bootstrap Complete

Successfully bootstrapped all core Kubernetes applications:
- Pushed talhelper encrypted secret to git repository
- Bootstrap apps completed successfully installing:
  - Cilium 1.17.5 (CNI networking)
  - CoreDNS 1.12.2 (DNS resolution)  
  - Spegel v0.3.0 (container registry mirror)
  - cert-manager v1.17.2 (TLS certificate management)
  - Flux operator and instance (GitOps)
- All Helm releases deployed successfully in ~3 minutes
- Flux is now syncing from Git repository

Cluster is fully operational with all core components running.

### 2025-06-29 - Post-Installation Verification Complete

Successfully completed all verification steps:
- Cilium networking healthy across all 3 nodes
- Flux GitOps operational with 16 Kustomizations applied
- Gateway connectivity verified (internal: 192.168.1.72, external: 192.168.1.73)
- DNS resolution working (echo.<domain> resolves via k8s_gateway)
- Wildcard TLS certificate (*.<domain>) issued and ready
- External-dns creating DNS records automatically

### 2025-06-29 - README Completion

Completed final README requirements:
- Configured GitHub webhook for immediate git push synchronization
- Applied `task template:tidy` to clean up template files
- Committed all changes to repository

README workflow fully complete. Cluster baseline established for service migrations.