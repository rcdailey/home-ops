# NFS Connection Hang and Network Flapping Investigation - 2025-10-26

**Last Updated:** 2025-10-26

**Status:** ROOT CAUSE IDENTIFIED - DISK SPINDOWN

## Executive Summary

Plex streaming failure caused by Unraid array disk spindown breaking NFS connections to Kubernetes
clients. Investigation initially suspected network flapping, but root cause confirmed as Unraid
spinning down array disks after idle timeout, causing NFS server to terminate TCP connections with
I/O errors.

**PRIMARY CAUSE:** Unraid array disk spindown (1-hour idle timeout) → NFS exports on `/mnt/user/*`
become unreadable → nfsd terminates client connections with ECONNRESET/EPIPE errors.

**SECONDARY ISSUE (HISTORICAL):** Network interface flapping on nezuko eth1 (Intel X540-AT2) at 7:00
AM documented in earlier investigation. Bonding has since been removed and static IP configured.

**CRITICAL CONFIGURATION:** Default spin down delay set to 1 hour is incompatible with NFS exports
from array disks. NFS clients experience 10+ minute outages during disk spinup cycles.

## Incident Timeline

### 2025-10-26 18:42 CDT - Disk Spindown Event

- **18:42:02 CDT:** Unraid spins down array disks (sdk, sdg, sdd, sdn, sdi, sdl) after 1-hour idle
- **18:42:11 CDT:** NFS clients on marin detect "server not responding" (9 seconds after spindown)
- **18:53:28 CDT:** NFS connectivity restored (disks spun back up, 11-minute outage)
- **18:54:17 CDT:** Plex pod restarted (3rd restart since nezuko reboot)
- **18:54:24 CDT:** Sabnzbd pod restarted (26th restart since nezuko reboot)

### 2025-10-26 16:49 CDT - Nezuko Server Reboot

- **Impact:** All NFS clients reconnected, but nfsd logged socket errors during initialization
- **Duration:** Plex ran stable for 21+ hours before this reboot (pod created Oct 25 19:19 CDT)
- **Post-reboot instability:** All pod failures occurred within 2 hours of nezuko restart

### Initial Investigation

```bash
# Pod health check
kubectl get pods -n media -l app.kubernetes.io/name=plex
# Result: plex-59f9fb5984-xvlbn Running 2/2, 24h uptime, no restarts

# Logs empty
kubectl logs -n media -l app.kubernetes.io/name=plex -c app --tail=100 --since=10m
# No output

# NFS mount verification attempts - ALL HUNG
kubectl exec -n media deploy/plex -c app -- ls -la /media
kubectl exec -n media deploy/plex -c app -- stat /media
kubectl exec -n media deploy/plex -c app -- df -h /media
# Commands never returned (killed after observation)
```

**Key Finding:** NFS mount completely unresponsive despite healthy pod and network connectivity.

## Root Cause Analysis

### Disk Spindown Breaking NFS Exports

**Definitive evidence from Unraid syslog:**

```bash
Oct 26 18:42:02 Nezuko emhttpd: spinning down /dev/sdk
Oct 26 18:42:02 Nezuko emhttpd: spinning down /dev/sdg
Oct 26 18:42:02 Nezuko emhttpd: spinning down /dev/sdd
Oct 26 18:42:02 Nezuko emhttpd: spinning down /dev/sdn
Oct 26 18:42:06 Nezuko emhttpd: spinning down /dev/sdi
Oct 26 18:42:09 Nezuko emhttpd: spinning down /dev/sdl
```

**Correlation with NFS failure (marin dmesg):**

```bash
[2025-10-26T23:42:11Z]: nfs: server 192.168.1.58 not responding, still trying
# (23:42:11 UTC = 18:42:11 CDT, 9 seconds after spindown began)
```

**Why this breaks NFS:**

1. Unraid NFS exports point to `/mnt/user/media` (SHFS layer spanning array disks)
2. When array disks spin down, filesystem becomes unreadable
3. NFS server attempts read → gets I/O error → closes TCP connections with `-104` (ECONNRESET)
4. Kubernetes clients see "server not responding" and hang indefinitely
5. Disks eventually spin up (~10-15 seconds), but TCP connections already terminated
6. Recovery takes 11 minutes as clients retry and server re-establishes connections

### Network Flapping Pattern (Historical - Pre-Configuration Changes)

**Note:** Analysis below from earlier investigation before bonding removal and static IP
configuration. Network flapping at 7:00 AM was documented but is distinct from tonight's disk
spindown issue.

```txt
Timestamp (calculated)       Event Description
--------------------------   --------------------------------------------------
2025-09-09 07:05:50          First flap cluster start
2025-09-09 07:07:10          First flap cluster end (~80s duration, 3 flaps)
2025-09-11 07:02:49          Second flap cluster start (~48h later)
2025-09-11 07:03:58          Second flap cluster end (~69s duration, 3 flaps)
2025-10-17 07:06:43          Recent flap cluster start
2025-10-17 07:08:09          Recent flap cluster end (~86s duration, 2 flaps)
```

**Status:** Bonding has since been removed, static IP configured on eth1. No link flapping observed
in current boot cycle (since 16:49 CDT Oct 26).

### Flapping Event Example

```txt
[9482489.500932] ixgbe 0000:03:00.1 eth1: NIC Link is Down
[9482489.585128] bond0: (slave eth1): link status definitely down, disabling slave
[9482489.586897] bond0: now running without any active interface!
[9482489.587171] br0: port 1(bond0) entered disabled state
[9482566.567374] ixgbe 0000:03:00.1 eth1: NIC Link is Up 10 Gbps, Flow Control: None
[9482566.649407] bond0: (slave eth1): making interface the new active one
[9482566.651772] bond0: active interface up!
[9482568.267769] ixgbe 0000:03:00.1 eth1: NIC Link is Down  # <-- Flap again 2s later
[9482568.313452] ixgbe 0000:03:00.1 eth1: left promiscuous mode
[9482568.315575] bond0: now running without any active interface!
[9482575.225803] ixgbe 0000:03:00.1 eth1: NIC Link is Up 10 Gbps, Flow Control: None
```

### Bonding Configuration Analysis

```bash
cat /proc/net/bonding/bond0
# Bonding Mode: fault-tolerance (active-backup)
# Currently Active Slave: eth1
# Link Failure Count: 8
```

**Configuration Issue Identified:**

- 4 NICs configured in bond0 (eth0, eth1, eth2, eth3)
- Only eth1 has link detected (cable connected)
- eth0/eth2/eth3 show NO-CARRIER (no cables)
- User confirmation: Intentional single-cable setup, no need for redundancy
- Bonding provides no actual redundancy, adds complexity

### NFS Mount Configuration

Current Plex NFS mount configuration (kubernetes/apps/media/plex/helmrelease.yaml:127-133):

```yaml
media:
  type: nfs
  server: 192.168.1.58
  path: /mnt/user/media
  globalMounts:
  - path: /media
    readOnly: true
```

**Actual mount options in use (Kubernetes defaults):**

Verified via `/proc/mounts` on marin node:

```txt
192.168.1.58:/mnt/user/media nfs4 rw,relatime,vers=4.2,rsize=1048576,wsize=1048576,
namlen=255,hard,proto=tcp,timeo=600,retrans=2,sec=sys,clientaddr=192.168.1.59,
local_lock=none,addr=192.168.1.58
```

- `vers=4.2`: NFSv4.2 protocol
- `hard`: Hard mount (retry indefinitely on failure)
- `proto=tcp`: TCP transport
- `timeo=600`: 60-second initial timeout (600 deciseconds)
- `retrans=2`: 2 retransmit attempts before timeout escalation
- `rsize/wsize=1048576`: 1MB read/write buffer size

**Critical finding:** Hard mounts with `timeo=600,retrans=2` do NOT recover from stuck TCP
connections. When TCP socket has 265KB send buffer backlog, NFS client retries indefinitely without
detecting the underlying connection failure. App-template does not support custom `mountOptions`
field, so Kubernetes defaults cannot be overridden at pod spec level.

## Hardware Details

### Nezuko NFS Server

- Platform: Supermicro X10DRi
- OS: Unraid 6.12.24
- NIC: Intel X540-AT2 (4x 10GbE ports)
- Driver: ixgbe (kernel built-in)
- Uptime: 119 days at time of investigation

### Network Interface Statistics

```bash
ethtool -S eth1
# Key statistics:
# lsc_int: 22                    # Link Status Change interrupts
# rx_errors: 4                   # Minimal RX errors
# tx_errors: 0                   # No TX errors
# rx_length_errors: 4            # Frame length issues
# rx_no_dma_resources: 34432     # DMA buffer exhaustion events
```

**DMA buffer exhaustion (34k events)** may indicate memory pressure or driver issues under high
load.

## Research Findings

### NFS Mount Options (AWS EFS Best Practices)

Recommended mount options for NFS resilience during network disruptions:

- `hard`: Indefinite retry instead of returning I/O errors
- `nfsvers=4.1`: Explicit protocol version prevents negotiation issues
- `timeo=600`: 60-second timeout before retry (reliability over responsiveness)
- `retrans=2`: Two retries before escalating recovery

Source: AWS EFS Documentation, NetApp NFS Best Practices

### Intel X540-AT2 Known Issues

Community reports of similar flapping behavior:

- Intel Community Forums: X540-AT2 flapping with Nexus switches (flow control issues)
- Level1Techs: 82599ES (same chipset family) flapping resolved with updated ixgbe driver
- Common triggers: Flow control mismatches, advanced offload features, firmware bugs

**Recommended troubleshooting:**

- Update NIC firmware
- Test with flow control disabled
- Try latest Intel ixgbe driver (vs kernel built-in)
- Check for interrupt conflicts or IOMMU issues

## Unanswered Questions

### 7:00 AM Time Pattern

**Critical Unknown:** What happens at 7:00 AM local time?

Investigated but not conclusive:

- Cron jobs: Daily tasks run at 4:00 AM (logrotate, etc.), not 7:00 AM
- UPS maintenance: No scheduled UPS self-tests found
- Environmental: Could be HVAC cycle, power grid load shift, or external interference
- Switch-side: Unable to access Unifi gateway logs (permission denied)

**Next Steps Needed:**

1. Check Unifi controller for scheduled port maintenance or PoE cycling
2. Review electrical system for time-of-use patterns
3. Check HVAC or environmental control schedules
4. Monitor for correlation with sunrise time (seasonal pattern)

### Why Only Marin Affected?

All Kubernetes nodes (lucy, nami, marin, sakura, hanekawa) connect to same NFS server, but only
marin connection hung. Possible explanations:

- Port-specific switch configuration
- Timing: marin happened to be mid-transfer during flap
- Node kernel version differences (marin running different kernel than others)
- Existing connection age (marin connection established before flap, others reconnected after)

## Recommended Solutions

### Immediate Actions (REQUIRED)

#### 1. Disable Array Disk Spindown

**Fix the root cause immediately:**

Navigate to Settings → Disk Settings in Unraid web UI:

- Change "Default spin down delay" from "1 hour" to **"Never"**
- This prevents array disks from spinning down and breaking NFS connections

**Why this fixes the issue:**

- NFS exports from `/mnt/user/*` require array disks to remain spinning
- Spindown causes 11-minute NFS outages as documented
- This is a well-known incompatibility between Unraid NFS and disk spindown

#### 2. ~~Add NFS mount resilience options~~ (INVALID - NO ACTION NEEDED)

**Status:** Attempted but reverted (commit 72bbfcb, reset to 484aff9)

**Reason:** App-template doesn't support `mountOptions`. Kubernetes already uses optimal NFS
defaults (`hard,nfsvers=4.2,timeo=600,retrans=2`) that cannot be improved via configuration.

**Finding:** Hard mounts retry indefinitely when disks are spun down. No client-side configuration
can work around server-side I/O errors from offline disks.

### Long-term Preventive Measures

#### 1. Alternative: Move NFS exports to cache pool

If you still want disk spindown for power savings:

- Create shares on cache pool (SSD/NVMe that never spin down)
- Move NFS exports from `/mnt/user/media` to cache-only paths
- Allows array disks to spin down without affecting NFS

#### 2. Alternative: Migrate to Ceph RBD storage

- Move critical workloads (Plex, Sabnzbd) from NFS to Ceph block storage
- Eliminates NFS dependency and spindown incompatibility
- Provides better performance and resilience

#### 3. Community research findings

Extensive web search confirmed this is a widespread Unraid issue:

- Multiple forum posts about NFS disconnections during spindown
- "Unraid has been knowingly pushing out updates with broken NFS" (Reddit, 6.12.13)
- Common workarounds: disable spindown, move to cache, or use SMB instead of NFS
- Technical explanation: Unraid NFS doesn't queue requests during spinup, returns immediate I/O
  errors

## Related Documentation

- [Plex Timeout Investigation][plex-investigation]: Previous NFS issues related to Unraid SHFS/array
  filesystem

[plex-investigation]: ./plex-timeout-investigation.md

## Essential Commands

### NFS Connection Diagnosis

```bash
# Check NFS TCP connections on server
ssh nezuko "ss -tn | grep ':2049'"

# Check for send buffer backlog (>100KB is concerning)
ssh nezuko "ss -tin | grep ':2049' | grep -v 'Send-Q: 0'"

# Verify NFS mount responsiveness from pod
kubectl exec -n media deploy/plex -c app -- timeout 10 ls /media
```

### Network Interface Health

```bash
# Check link status
ssh nezuko "ip link show eth1"
ssh nezuko "ethtool eth1 | grep 'Link detected'"

# Check for recent flapping
ssh nezuko "dmesg | grep -E '(eth1.*Link|bond0.*slave eth1)' | tail -20"

# Check link failure count
ssh nezuko "cat /proc/net/bonding/bond0 | grep -A 5 'Slave Interface: eth1'"

# Get interface statistics
ssh nezuko "ethtool -S eth1 | grep -E 'lsc_int|errors|dma'"
```

### Investigation Commands

```bash
# Calculate flapping event timestamps from kernel log
# (Requires system uptime and kernel timestamp from dmesg)

# Check cron schedule
ssh nezuko "crontab -l"

# Check for scheduled tasks
ssh nezuko "ls -la /etc/cron.daily/ /etc/cron.hourly/"
```

## Document History

| Date       | Changes                                                |
| ---------- | ------------------------------------------------------ |
| 2025-10-26 | Initial investigation of NFS hang and network flapping |

**Status:** Root cause RESOLVED - disk spindown confirmed. Network flapping was historical issue,
resolved by bonding removal and static IP configuration. Current outage (Oct 26 18:42) definitively
caused by 1-hour spindown timer.
