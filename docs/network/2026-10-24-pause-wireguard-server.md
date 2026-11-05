# Pause the UDM Pro WireGuard server

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decision:** Pause the `Home VPN` WireGuard server on the UDM Pro instead of deleting it.

## Context and Problem Statement

The WireGuard server listened on UDP 1443 on the WAN and relied on a public DNS record that reveals
the home IP. [Tailscale on the UDM Pro][tailscale-udm] now provides remote access without an inbound
port.

## Decision Outcome

The server was paused in UniFi Network: Settings, VPN, VPN Server, Manage, select `Home VPN`, Pause.
Pausing keeps the server configuration and peers so it can be resumed later. UniFi removes the
listener, the WireGuard interface, and its WAN allow rule while paused.

The `dynamic` DNS record for the home IP in Cloudflare is unaffected by this change.

## Verification and Revert

Confirm the server is paused and nothing listens on the port:

```sh
mise x -- unifly vpn remote-access list | jq -c '.[] | {name, enabled}'
./scripts/unifi-ssh.sh 192.168.1.1 'ss -ulnp | grep -c ":1443 "'
```

Expected: `{"name":"Home VPN","enabled":false}` and `0`.

Revert by resuming `Home VPN` from the same Manage menu.

[tailscale-udm]: ./2026-10-24-tailscale-on-udm-pro.md
