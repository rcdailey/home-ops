Based on my research of current Talos Linux documentation and community reports, here's comprehensive troubleshooting information for Talos Image Factory and Intel i915 extension issues in 2025:

## 1. Current Image Factory Status

The Talos Image Factory at [factory.talos.dev](https://factory.talos.dev) appears to be operational as of July 2025. [^1][^2] Recent Talos releases including v1.10.5 (released July 3, 2025) confirm active development and infrastructure maintenance. [^2]

However, some users report specific issues:
- Download speed problems (~100 Kbps) due to lack of CDN distribution [^3]
- Intermittent connectivity issues from certain networks [^4]
- Registry pull failures in some environments [^4][^5]

The Image Factory infrastructure remains the primary official source with no major announced outages.

## 2. Intel i915 Extension Availability

**Critical Change in Talos 1.9.0**: The i915 DRM drivers were completely removed from the Talos base image and moved to a system extension named ```i915```. [^6][^7]

| Extension Status | Details |
|-----------------|---------|
| Current Extension Name | ```i915``` (not ```i915-ucode```) |
| Compatibility | Talos v1.9.x, v1.10.4, v1.10.5 |
| Previous Extension | ```i915-ucode``` (retired in v1.9.0) |
| Auto-upgrade | Image Factory/Omni automatically migrates from old extension |

The extension name ```i915``` is correct for current versions. [^6][^7] Intel UHD Graphics 620 should be supported through this extension. [^6]

## 3. Alternative Image Factory Sources

Limited alternatives exist beyond factory.talos.dev:

| Source Type | Details |
|-------------|---------|
| Community Mirrors | [talos.fastcup.cloud](https://talos.fastcup.cloud) (CloudFlare CDN mirror) [^3] |
| Private Registries | Users can mirror factory images to local registries [^8] |
| Custom Builds | Building custom Talos images with embedded extensions [^9] |

Most alternative sources are mirrors of the official factory rather than independent image builders. For air-gapped environments, users typically pull from factory.talos.dev and push to internal registries. [^10]

## 4. Extension Compatibility Matrix

| Talos Version | i915 Extension Status | Notes |
|---------------|----------------------|-------|
| 1.8.x and earlier | Built into base image | No extension needed |
| 1.9.x | ```i915``` system extension | Major architecture change |
| 1.10.x | ```i915``` system extension | Continued support |

**Important**: Starting with Talos 1.10, the ```.machine.install.extensions``` configuration is deprecated. [^11] Extensions must be included via Image Factory boot assets, not installed post-boot.

## 5. Troubleshooting Image Factory 404 Errors

Common causes of 404 errors:

| Issue | Solution |
|-------|---------|
| Invalid Schematic ID | Verify schematic was uploaded: ```curl -X POST --data-binary @schematic.yaml https://factory.talos.dev/schematics``` [^12] |
| Incorrect URL Format | Use format: ```https://factory.talos.dev/image/{schematic-id}/{version}/{target}``` [^12] |
| Version Incompatibility | Check extension compatibility with Talos version in factory UI [^12] |
| Extension Not Available | Some extensions aren't available for all Talos versions [^12] |

**Valid URL Examples**:
- ISO: ```https://factory.talos.dev/image/376567988ad370138ad8b2698212367b8edcb69b5fd68c80be1f2ec7d603b4ba/v1.10.3/metal-amd64.iso``` [^12]
- Installer: ```factory.talos.dev/installer/376567988ad370138ad8b2698212367b8edcb69b5fd68c80be1f2ec7d603b4ba:v1.10.3``` [^12]

To verify schematic ID from running installation:
```bash
talosctl get extensions
```
This shows the schematic ID in the extension list. [^12]

## 6. Alternative Intel GPU Setup Methods

**Important Limitation**: In Talos 1.10+, system extensions cannot be loaded post-boot. [^11][^13] Extensions must be included at image generation time via Image Factory.

| Method | Availability | Notes |
|--------|-------------|-------|
| Post-boot Extension Loading | Not supported in 1.10+ | Deprecated functionality |
| Custom Image Building | Available | Build Talos images with embedded extensions [^9] |
| Local Registry Mirror | Recommended | Mirror factory images with extensions [^8] |
| Air-gapped Installation | Supported | Pre-pull images to internal registry [^10] |

For immediate workaround if Image Factory is unavailable:
1. Use community mirrors like talos.fastcup.cloud [^3]
2. Build custom images with embedded i915 extension [^9]
3. Set up local registry mirror of factory images [^8]

**Working 2025 Example**:
Create schematic with i915 extension:
```yaml
customization:
systemExtensions:
  officialExtensions:
    - siderolabs/i915
```

Upload to factory and use the returned schematic ID in your installation URLs. [^12]

The key change is that Intel GPU support now requires the ```i915``` system extension (not ```i915-ucode```) and must be included at boot time via Image Factory rather than post-installation configuration.

[^1]: [Talos Linux Image Factory](https://factory.talos.dev/#:~:text=The%20Talos,Talos%20Linux.)
[^2]: [Releases · siderolabs/talos - GitHub](https://github.com/siderolabs/talos/releases#:~:text=Talos%201.10.5,issues%20at)
[^3]: [Download speeds from factory.talos.dev are extremely slow](https://github.com/siderolabs/image-factory/issues/173#:~:text=When%20downloading,I%27m%20consi)
[^4]: [Cannot Pull from talos image factory](https://github.com/siderolabs/talos/issues/11219#:~:text=Bug%20Report,to%20factory.talos.dev)
[^5]: [Installing from insecure (http) registry · siderolabs talos ...](https://github.com/siderolabs/talos/discussions/11294#:~:text=Hello%2C%20I%27m,factory.talos.dev%20registry.)
[^6]: [What's New in Talos 1.9.0](https://www.talos.dev/v1.9/introduction/what-is-new/#:~:text=%23%20What%27s,the%20%60i9)
[^7]: [move out of base i915/amdgpu drivers to the extensions](https://github.com/siderolabs/talos/issues/9728#:~:text=With%20i915%2C,-%3E%20i915)
[^8]: [Download speeds from factory.talos.dev are extremely slow](https://github.com/siderolabs/image-factory/issues/173#:~:text=Since%20factory.talos.dev,Page%20Rules.)
[^9]: [Problem with nvidia extension - Modules not found · siderolabs talos ...](https://github.com/siderolabs/talos/discussions/9886#:~:text=Thank%20you,solved%20it.)
[^10]: [Building Custom Talos Images | TALOS LINUX](https://www.talos.dev/v1.10/advanced/building-images/#:~:text=Talos%20container,docker%20login%29.)
[^11]: [Air-gapped Environments | TALOS LINUX](https://www.talos.dev/v1.10/advanced/air-gapped/#:~:text=Launching%20Talos,specified%20endpoint.)
[^12]: [What's New in Talos 1.10.0 | TALOS LINUX](https://www.talos.dev/v1.10/introduction/what-is-new/#:~:text=System%20Extensions,in%20non)
[^13]: [Image Factory](https://www.talos.dev/v1.10/learn-more/image-factory/#:~:text=ta%3A%22mydata%22%20%60%60%60,Talos%20Linux)
[^14]: [Image Factory](https://www.talos.dev/v1.10/learn-more/image-factory/#:~:text=and%20a,schematic%29%20%3Chttps%3A//factory.talos.dev/image/376567988ad370138ad8)
[^15]: [Image Factory](https://www.talos.dev/v1.10/learn-more/image-factory/#:~:text=include%20every,Factory%20UI%5D%28https%3A//www.talos.dev/v1.10/)
[^16]: [Image Factory](https://www.talos.dev/v1.10/learn-more/image-factory/#:~:text=schematic%2C%20architecture,Talos%20Linux)
[^17]: [Image Factory](https://www.talos.dev/v1.10/learn-more/image-factory/#:~:text=provides%20a,the%20schematic)
[^18]: [System Extensions](https://www.talos.dev/v1.10/talos-guides/configuration/system-extensions/#:~:text=The%20document,Image%20Factory.)
[^19]: [Image Factory](https://www.talos.dev/v1.10/learn-more/image-factory/#:~:text=the%20ID,implementationdata%3A%22mydata%22%20%60%60)
