# yaml-language-server: $schema=https://raw.githubusercontent.com/siderolabs/talos/refs/heads/main/pkg/machinery/config/schemas/config.schema.json
# topf injects installer.image from talosVersion and schematicId in topf.yaml.
---
apiVersion: v1alpha1
kind: UnattendedInstallConfig
provisioning:
  diskSelector:
    match: disk.model == "{{ .Node.Data.diskModel }}"
  wipe: false
