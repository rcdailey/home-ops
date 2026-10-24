# Tailscale subnet router and exit node on the UDM Pro

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decision:** Run Tailscale on the UDM Pro with [tailscale-unifi][tailscale-unifi] as a subnet
  router for the Main LAN and K8s Cluster networks and as an optional exit node.

## Context and Problem Statement

Remote access used the UDM's WireGuard server. It needs an inbound WAN port and a public DNS record
that reveals the home IP. Many hotel and public networks also block its UDP traffic.

Internal services are not exposed to the WAN, so remote devices need routed access to the home
networks, and occasionally a full tunnel on untrusted networks.

## Considered Options

- **Tailscale Kubernetes operator** - a `Connector` with `exitNode: true`, managed by GitOps. A
  cluster outage removes remote access when it is needed to repair the cluster.
- **Tailscale on the UDM Pro** - unofficial, but independent of the cluster.
- **UniFi Teleport** - no open port, but no documented fallback when UDP is blocked.

## Decision Outcome

Chosen option: **Tailscale on the UDM Pro**, because remote access must survive cluster outages.
Tailscale needs no inbound port and falls back to its DERP relays over HTTPS when UDP is blocked.

Configuration:

```sh
tailscale up --advertise-routes=192.168.1.0/24,192.168.50.0/24 --advertise-exit-node \
  --hostname=udm-pro
```

Guest, IoT, Kids, Work, and Cameras networks are not advertised. In the Tailscale admin console,
both routes and the exit node are approved, key expiry is disabled for `udm-pro`, and split DNS
sends `${SECRET_DOMAIN}` queries to `192.168.1.1`.

## Consequences

- Good, because remote access no longer depends on the cluster or an open WAN port.
- Good, because the package installs updates automatically (`TAILSCALE_AUTOUPDATE="true"`).
- Bad, because the install is unofficial; Ubiquiti support may attribute problems to it.
- Bad, because a firmware update can remove the binary. A systemd timer reinstalls it about two
  minutes after boot, which needs access to `pkgs.tailscale.com`; node state in
  `/data/tailscale/tailscaled.state` survives, so no new login is needed.

## Verification and Revert

After each firmware update, confirm Tailscale runs and serves both routes:

```sh
./scripts/unifi-ssh.sh 192.168.1.1 tailscale status --json | jq -c '.Self.PrimaryRoutes'
```

Expected: `["192.168.1.0/24","192.168.50.0/24"]`.

Revert:

```sh
./scripts/unifi-ssh.sh 192.168.1.1 /data/tailscale/manage.sh uninstall
```

Then remove `udm-pro` from the Tailscale admin console.

## References

- [tailscale-unifi][tailscale-unifi]
- [Tailscale subnet routers][ts-subnets]
- [Tailscale exit nodes][ts-exit-nodes]

[tailscale-unifi]: https://github.com/SierraSoftworks/tailscale-unifi
[ts-subnets]: https://tailscale.com/kb/1019/subnets
[ts-exit-nodes]: https://tailscale.com/kb/1103/exit-nodes
