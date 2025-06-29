# Session: Talos Kubernetes Cluster Setup

## Status

- **Phase**: Talos Bootstrap Complete
- **Progress**: 4/15 major stages complete

## Objective

Deploy a 3-node Talos Kubernetes cluster with Flux GitOps, following the cluster-template README workflow. Migrate from existing docker-compose setup on Nezuko to Kubernetes while maintaining external access through Cloudflare tunnel.

## Current Focus

Talos bootstrap successful. Next: Push talhelper secret to git, then bootstrap Kubernetes applications.

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

### Phase 5: Bootstrap Talos, Kubernetes, and Flux ✅🔄
- [x] Boot nami and marin from Talos ISO using USB/KVM
- [x] Run `task bootstrap:talos` to install Talos on all nodes  
- [ ] **NEXT STEP**: Push talhelper encrypted secret to git
- [ ] Run `task bootstrap:apps` to install cilium, flux, etc.
- [ ] Watch cluster rollout with `kubectl get pods --all-namespaces --watch`

### Phase 6: Post-Installation Verification
- [ ] Check Cilium status: `cilium status`
- [ ] Verify Flux: `flux check`, `flux get sources git flux-system`
- [ ] Test connectivity to gateways (192.168.1.72, 192.168.1.73)
- [ ] Verify DNS resolution for echo.<domain>
- [ ] Check wildcard certificate status
- [ ] Configure GitHub webhook for flux-webhook.<domain>

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

1. **Physical access required**: Boot nami (192.168.1.50) and marin (192.168.1.59) from Talos ISO using USB drives
2. Once both nodes boot into Talos maintenance mode, run `task bootstrap:talos`
3. Continue with Phase 5 bootstrap steps

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

All nodes now running Talos and ready for Kubernetes applications.
Next: Push talhelper secret to git, then bootstrap apps with `task bootstrap:apps`.