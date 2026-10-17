# yaml-language-server: $schema=https://raw.githubusercontent.com/siderolabs/talos/refs/heads/main/pkg/machinery/config/schemas/config.schema.json
---
apiVersion: v1alpha1
kind: LinkAliasConfig
name: eth-main
selector:
  match: mac(link.permanent_addr) == "{{ .Node.Data.mac }}"
---
apiVersion: v1alpha1
kind: BondConfig
name: bond0
links:
  - eth-main
bondMode: active-backup
mtu: 1500
addresses:
  - address: {{ .Node.IP }}/24
routes:
  - gateway: 192.168.1.1
---
apiVersion: v1alpha1
kind: HostnameConfig
auto: "off"
hostname: {{ .Node.Host }}
