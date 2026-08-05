---
name: unifi-operations
description: >-
  Use when querying or changing UniFi Network configuration with `unifly`; inspecting firewall
  policies, networks, clients, zones, or site settings; using `scripts/unifi-ssh.sh`; or diagnosing
  a UniFi API limitation. Do NOT use for Kubernetes networking or application HTTPRoutes.
---

# UniFi operations

Use `unifly` before lower-level access. Run the relevant `--help`, request structured output when
available, and read current state before changing it.

## Access order

1. Use `unifly` for firewall policies, networks, clients, zones, and settings.
2. Use `scripts/unifi-ssh.sh` only when device-level inspection is required.
3. Use direct database queries only when `unifly` lacks the operation and the task cannot be
   completed through supported interfaces.

Do not replace a failed supported operation with raw HTTP or database access. Stop and report the
failure unless a known limitation below applies.

## Site settings

`unifly settings set <key> <field> <value>` uses the session API. Re-read the setting after every
mutation and verify the requested value took effect.

The mDNS site setting is a known exception. All available API paths silently ignore changes to
`enabled_for_network_ids`. Change mDNS VLAN scope through the UniFi UI at Settings, Networks,
Gateway mDNS Proxy. Do not claim an API mutation succeeded based only on its exit status.

## Direct database fallback

The UDM is at `192.168.1.1`. Its MongoDB service uses port `27117` and database `ace`. Treat direct
queries as a read-only diagnostic fallback unless the user explicitly approves a mutation and no
supported interface exists.
