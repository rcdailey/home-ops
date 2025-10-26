# NFS Connection Hang and Network Flapping Investigation - 2025-10-26

**Last Updated:** 2025-10-26

**Status:** PARTIAL ROOT CAUSE IDENTIFIED

## Executive Summary

Plex streaming failure caused by TCP connection hang between Kubernetes node marin (192.168.1.59)
and Unraid NFS server nezuko (192.168.1.58). Investigation revealed network interface flapping on
nezuko's eth1 (Intel X540-AT2) occurring in predictable patterns around 7:00 AM local time.

**PRIMARY CAUSE:** NFS TCP socket stuck with 265KB send buffer backlog to marin after network
disruption.

**UNDERLYING ISSUE:** Network interface flapping on nezuko eth1 with unknown root cause (time-based
pattern suggests environmental or scheduled trigger).

**CONFIGURATION ISSUE:** Bonding configured for 4 NICs but only 1 cable connected (eth1), creating
false sense of redundancy.

## Incident Timeline

### 2025-10-26 ~14:00 CST - Streaming Failure

- **Trigger:** User streaming Foundation on Plex
- **Symptom:** Stream stopped mid-playback, no error message
- **Duration:** Approximately 2-5 minutes before user reported

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

### TCP Connection Backlog

Investigation of nezuko NFS server revealed stuck TCP connection:

```bash
ssh nezuko "ss -tn | grep -E ':(2049|111)'"
# Output:
# ESTAB 0      264728  192.168.1.58:2049  192.168.1.59:691   # marin - STUCK
# ESTAB 0      0       192.168.1.58:2049  192.168.1.62:838   # sakura - healthy
# ESTAB 0      0       192.168.1.58:2049  192.168.1.54:746   # lucy - healthy
# ESTAB 0      0       192.168.1.58:2049  192.168.1.63:794   # hanekawa - healthy
# ESTAB 0      0       192.168.1.58:2049  192.168.1.50:1012  # nami - healthy
```

**265KB send buffer backlog** on connection to marin (Plex host node) while all other Kubernetes
nodes show healthy connections (0 backlog).

### Network Flapping Pattern

Analysis of nezuko kernel logs revealed eth1 link flapping history:

```txt
Timestamp (calculated)       Event Description
--------------------------   --------------------------------------------------
2025-09-09 07:05:50          First flap cluster start
2025-09-09 07:07:10          First flap cluster end (~80s duration, 3 flaps)
2025-09-11 07:02:49          Second flap cluster start (~48h later)
2025-09-11 07:03:58          Second flap cluster end (~69s duration, 3 flaps)
2025-10-17 07:06:43          Recent flap cluster start (9 days ago)
2025-10-17 07:08:09          Recent flap cluster end (~86s duration, 2 flaps)
```

**Critical Pattern:** All flapping events occur between 7:00-7:10 AM local time. This temporal
clustering suggests scheduled task, environmental factor, or external trigger rather than random
hardware failure.

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

**Missing resilience options:**

- No mount options specified (using all defaults)
- No NFS version pinning
- No timeout configuration
- No retry behavior defined

When TCP connection hangs, Kubernetes NFS client has no recovery mechanism.

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

### Immediate Actions

#### 1. Add NFS mount resilience options

Edit kubernetes/apps/media/plex/helmrelease.yaml:

```yaml
media:
  type: nfs
  server: 192.168.1.58
  path: /mnt/user/media
  mountOptions:
    - hard
    - nfsvers=4.1
    - timeo=600
    - retrans=2
  globalMounts:
  - path: /media
    readOnly: true
```

Rationale: Provides application-layer recovery when TCP connections hang. NFS client can detect and
recover from stuck connections without manual intervention.

#### 2. Investigate 7:00 AM trigger

- Access Unifi controller web interface
- Check for scheduled tasks, port maintenance windows, or PoE cycling
- Review switch logs for eth1 port events
- Check for HVAC, UPS, or electrical system schedules

#### 3. Simplify bonding configuration

Since only one cable is connected and redundancy is not needed:

```bash
# Option A: Remove bonding entirely, use eth1 directly
# Option B: Keep bonding but set primary explicitly
echo eth1 > /sys/class/net/bond0/bonding/primary
```

Reduces complexity and potential bonding-related timing issues.

### Long-term Preventive Measures

#### 1. Monitor NFS connection health

Create alert for TCP send buffer backlog on NFS connections:

```bash
ss -tn | grep ':2049' | awk '$2 > 100000 {print "ALERT: NFS send buffer backlog:", $2}'
```

#### 2. Network interface monitoring

Alert on link state changes:

```bash
# Monitor for "Link is Down" events in dmesg
dmesg | grep -i "link is down" | tail -20
```

#### 3. Consider infrastructure changes

- Dedicated NAS with native ZFS/NFS support (related to previous investigation)
- Migrate from Unraid array NFS to ZFS pool NFS (eliminates SHFS issues from previous incident)
- Network path redundancy with actual cabling (if needed)

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

**Status:** Network flapping root cause still unknown. 7:00 AM time pattern requires further
investigation of environmental factors and switch-side configuration.
