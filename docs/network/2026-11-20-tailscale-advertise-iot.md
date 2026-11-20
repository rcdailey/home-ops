# Advertise the IoT network through Tailscale on the UDM Pro

- **Date:** 2026-11-20
- **Change:** The UDM Pro now advertises the IoT network (`192.168.2.0/24`) as a Tailscale subnet
  route, alongside the Main LAN and K8s Cluster routes from the
  [original Tailscale record][original].

## Reason

Remote devices could not reach IoT devices such as the OpenSprinkler controller at `192.168.2.108`.
Selecting `udm-pro` as an exit node does not help: an exit node forwards internet traffic but does
not give access to its local networks, which require advertised subnet routes.

This gives every tailnet device routed access to the IoT network. Guest, Kids, Work, and Cameras
remain unadvertised.

## Change

Run on the UDM Pro; `tailscale set` changes only this preference and keeps the exit node and
hostname:

```sh
./scripts/unifi-ssh.sh 192.168.1.1 tailscale set \
  --advertise-routes=192.168.1.0/24,192.168.50.0/24,192.168.2.0/24
```

Then approve `192.168.2.0/24` in the Tailscale admin console under Machines, `udm-pro`, Edit route
settings.

## Verification and Revert

```sh
./scripts/unifi-ssh.sh 192.168.1.1 tailscale status --json | jq -c '.Self.PrimaryRoutes'
```

Expected after approval: `["192.168.1.0/24","192.168.2.0/24","192.168.50.0/24"]`. From a remote
tailnet device, `http://192.168.2.108/` should load the OpenSprinkler page.

Revert:

```sh
./scripts/unifi-ssh.sh 192.168.1.1 tailscale set \
  --advertise-routes=192.168.1.0/24,192.168.50.0/24
```

Then remove the route from `udm-pro` in the admin console.

[original]: 2026-10-24-tailscale-on-udm-pro.md
