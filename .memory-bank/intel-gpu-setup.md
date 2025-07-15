# Session: Intel GPU Setup for Talos Kubernetes Cluster

## Status

- **Phase**: Implementation
- **Progress**: 7/8 items complete

## Objective

Enable Intel integrated GPU hardware acceleration support on Intel NUC nodes (nami, marin) in the Talos Kubernetes cluster for future media transcoding workloads (Plex, Jellyfin).

## Current Focus

Testing Intel GPU plugin deployment and verifying GPU resource allocation

## Task Checklist

- [x] Create Intel GPU extension patch for Talos
- [x] Update talconfig.yaml to include GPU patch
- [x] Generate and apply Talos configuration to Intel nodes
- [x] Validate GPU detection on hardware level
- [x] Deploy Node Feature Discovery for hardware detection
- [x] Resolve Talos Image Factory and Flux deployment issues
- [x] Create custom NodeFeatureRule for Intel GPU labeling
- [x] Create Intel GPU device plugin Kubernetes application
- [ ] Test GPU resource allocation

## Next Steps

1. Commit and push Intel GPU plugin configuration
2. Validate GPU plugin deployment and GPU resources appear in Kubernetes (intel.com/gpu: 1)
3. Apply GPU configuration to marin node
4. Test end-to-end GPU resource allocation with media transcoding workloads

## Resources

### Hardware Capabilities
- **nami (i7-8559U)**: Intel Iris Plus Graphics 655 - Superior transcoding (8-12 streams)
- **marin (i5-8259U)**: Intel UHD Graphics 620 - Good transcoding (6-10 streams)
- **rias (QEMU Virtual)**: No GPU support (excluded from setup)

### Talos Configuration
- **Base Image**: `376567988ad370138ad8b2698212367b8edcb69b5fd68c80be1f2ec7d603b4ba` (rias VM)
- **GPU Image**: `039535a70c3bd1667c355eca78571267704e55c8a24785033d183b8f26e39d82` (nami, marin)
- **Extensions**: `siderolabs/i915`, `siderolabs/intel-ucode`, `siderolabs/mei`

### CLI Tools Discovered
- `talhelper genurl installer --extension i915` - generates proper factory URLs
- `--offline-mode` - validates extension names without API calls
- Extension name confirmed as `i915` (not `siderolabs/i915`)

### Current Issue Analysis
- Talos successfully applied GPU configuration to nami node
- Node rebooted but i915 module fails to load: "module not found"
- Image Factory URLs returning 404 for both original and GPU schematics
- CLI tools generate correct schematic ID but factory.talos.dev seems inaccessible

### File Locations
- GPU patch: `talos/patches/global/machine-gpu.yaml`
- Main config: `talos/talconfig.yaml`
- Generated configs: `talos/clusterconfig/kubernetes-*.yaml`

## Progress & Context Log

### 2025-07-14 - Session Created
Created session to implement Intel GPU support for Talos cluster. Research identified need for i915 system extension and Intel GPU device plugin for Kubernetes integration.

### 2025-07-14 - Memory Configuration Optimization Complete
Successfully updated memory limits for all applications based on research:
- PostgreSQL: 256Mi request, 512Mi limit (reduced from 500 to 100 max_connections)
- Echo: 64Mi request, 96Mi limit (prevented OOM at 84% usage)
- Authentik Server: 512Mi request, 1Gi limit
- Authentik Worker: 400Mi request, 750Mi limit (user-optimized)
- Redis: 64Mi request, 128Mi limit
- QBittorrent: 128Mi request, 512Mi limit (reduced from 4Gi waste)
- Homer: 32Mi request, 64Mi limit

### 2025-07-14 - Intel GPU Research Complete
Comprehensive research revealed proper Intel GPU setup for Talos:
- Intel UHD Graphics 620/Iris Plus Graphics 655 support hardware transcoding
- Requires i915 system extension via Image Factory (not machine.install.extensions)
- Need Intel GPU device plugin for Kubernetes resource management
- Custom NodeFeatureRule required for Talos built-in i915 detection

### 2025-07-14 - Talos Configuration Applied to nami
Successfully created and applied Intel GPU configuration:
- Created machine-gpu.yaml patch with i915 kernel module
- Generated new Image Factory schematic with i915 extension
- Updated nami and marin to use GPU-enabled factory image
- Applied configuration to nami node - successful reboot

### 2025-07-14 - GPU Detection Issues Discovered
Hardware validation revealed critical issues:
- nami node shows "error loading module i915: module not found"
- No /dev/dri devices created despite successful configuration apply
- Image Factory URLs return 404 errors (both original and GPU schematics)
- CLI tools work correctly but factory.talos.dev appears inaccessible

### 2025-07-14 - CLI Investigation Complete
Discovered proper Talos tooling for Image Factory integration:
- talhelper has built-in Image Factory support via genurl command
- Extension name confirmed as "i915" (simple name, not prefixed)
- Generated schematic ID: 7d4575c31f2a38ce528a25aa9161e0c979f5557a20d68f05f6616c48eee582fd
- Issue appears to be Image Factory service availability, not configuration

### 2025-07-15 - Intel GPU Extension Setup Complete
Successfully resolved Image Factory issues and deployed proper Intel GPU support:
- Used onedr0p recommendation: siderolabs/i915 + intel-ucode + mei extensions
- Generated new GPU schematic: 039535a70c3bd1667c355eca78571267704e55c8a24785033d183b8f26e39d82
- Removed redundant machine-gpu.yaml patch (extensions auto-load kernel modules)
- Applied GPU configuration to nami node successfully
- Verified Intel Iris Plus Graphics 655 detection with /dev/dri devices created

### 2025-07-15 - Node Feature Discovery Deployment Complete
Successfully deployed NFD for Intel GPU hardware detection:
- Fixed repository URL: kubernetes-sigs.github.io/node-feature-discovery/charts
- Resolved Flux reconciliation deadlock with controller restarts
- NFD v0.17.3 deployed with master + 3 worker pods running
- Added NodeFeatureRule for custom Intel GPU labeling

### 2025-07-15 - Intel GPU Device Plugin Configuration Complete
Successfully created Intel GPU device plugin using app-template approach:
- Fixed HelmRelease structure to use chartRef instead of chart.spec.sourceRef
- Configured DaemonSet with node selector for custom-intel-gpu=true nodes
- Added proper hostPath mounts for /dev/dri, /sys/class/drm, kubelet sockets
- Set dependency on node-feature-discovery for proper startup order
- All pre-commit validations pass - ready for deployment testing
