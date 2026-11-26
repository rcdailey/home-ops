# Reserve DHCP addresses for admin workstations

- **Date:** 2026-11-26
- **Change:** `robert-pc` (`04:7c:16:b6:0f:30`) now has a DHCP reservation for `192.168.1.149`.
  `robert-mbp` (`2e:cf:a0:70:2b:2c`) already had one for `192.168.1.247`.

## Reason

A Windows PC on the Kids network accepts SSH (used by `scripts/rps.sh`) only from these two
addresses. Its Windows Firewall rule filters by source IP, because traffic from Main LAN is routed
through the UDM and reaches the PC with the gateway's MAC address, so a MAC filter on the PC cannot
identify the workstation. Without reservations, DHCP could move either workstation to an address the
rule does not allow.

## Change

```sh
unifly clients set-ip 04:7c:16:b6:0f:30 --ip 192.168.1.149
```

The PC's rule was set to match, through `scripts/rps.sh`:

```powershell
Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -RemoteAddress 192.168.1.149, 192.168.1.247
```

## Verification and Revert

```sh
unifly clients get 04:7c:16:b6:0f:30 -o json-compact | jq -c '{name, fixed_ip, use_fixedip}'
unifly clients get 2e:cf:a0:70:2b:2c -o json-compact | jq -c '{name, fixed_ip, use_fixedip}'
```

Expected: `use_fixedip` is `true`, with the addresses above.

Revert:

```sh
unifly clients remove-ip 04:7c:16:b6:0f:30
```
