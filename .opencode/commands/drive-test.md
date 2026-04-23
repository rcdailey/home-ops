---
description: Prime session with drive diagnostic knowledge for SSD/HDD testing
---

Prime the session for drive diagnostics. Verify tooling is installed and functional, then load
reference material so the session can respond to testing instructions without guesswork.

Arguments: $ARGUMENTS (unused; context is injected unconditionally)

## 1. Preflight: Tool Installation and Capabilities

Run these checks immediately on command invocation. Fix problems before reporting readiness.

### Required tools

| Tool      | Binary                | Package (dnf) | Package (brew)          | Purpose                |
| --------- | --------------------- | ------------- | ----------------------- | ---------------------- |
| smartctl  | `/usr/sbin/smartctl`  | smartmontools | smartmontools           | SMART health data      |
| fio       | `/usr/bin/fio`        | fio           | fio                     | Performance benchmarks |
| badblocks | `/usr/sbin/badblocks` | e2fsprogs     | (preinstalled on Linux) | Surface scan           |

Check each binary with `which`. All three are installed via brew. If any is missing, install with
`brew install <package>`.

### Group membership

Check `groups` output for `disk`. The user is already in the `disk` group. If missing, stop and tell
the user (requires a one-time `usermod` and session restart).

### Capabilities

Check `getcap /usr/sbin/smartctl /usr/bin/fio`. Both must show `cap_sys_rawio=ep`.

A systemd path unit (`disk-diag-caps.path`) watches these binaries and re-applies capabilities
automatically after package upgrades. If capabilities are missing, run `systemctl start
disk-diag-caps.service` and recheck.

### USB dock driver mode

If a USB drive is connected (`TRAN=usb` in `lsblk`), verify the JMS578 is using BOT mode:

```bash
lsusb -t | grep "Mass Storage"
```

Must show `Driver=usb-storage`. If it shows `Driver=uas`, follow the runtime fix in the JMS578 UAS
Bug gotcha section before proceeding.

### Preflight report

After all checks pass, print a compact status:

```txt
Drive test session ready
  smartctl: ok (cap_sys_rawio)
  fio: ok (cap_sys_rawio)
  badblocks: ok
  disk group: ok
  usb dock: ok (usb-storage/BOT)
Awaiting instructions.
```

If no USB drive is connected, omit the usb dock line. All preflight checks should pass without
privilege escalation. If any check fails, report clearly and stop.

## Environment

- **USB dock**: Sabrent EC-DFLT (JMicron JMS578 bridge, USB ID `152d:a578`)
- **User group**: `disk` (required for `/dev/sd*` and `/dev/sg*` access)
- **Capabilities**: `disk-diag-caps.path` systemd unit auto-applies `CAP_SYS_RAWIO` to smartctl/fio
- **dmesg**: unrestricted (`kernel.dmesg_restrict=0` via `/etc/sysctl.d/`)
- **UAS quirk**: persistent via `/etc/modprobe.d/jms578-disable-uas.conf` (baked into initramfs)
- **Privilege**: none required for normal operation

## Gotchas

### JMS578 UAS Bug (Critical)

The JMS578 bridge has a buggy UAS (USB Attached SCSI) driver implementation that causes severe
issues under load: multi-second read stalls, 30-second IO outliers (matching the SCSI command
timeout), and completely broken fdatasync (FLUSH CACHE passthrough fails). Symptoms: sequential
reads at ~34 MB/s instead of ~400 MB/s, `uas_eh_abort_handler` floods in `dmesg`, and fdatasync
tests completing 1 IO in 30 seconds.

**Fix: disable UAS and force BOT (Bulk-Only Transport) mode.**

The UAS quirk is configured persistently via `/etc/modprobe.d/jms578-disable-uas.conf` and baked
into the initramfs. The preflight check verifies BOT mode is active. If `Driver=uas` appears despite
the persistent config (e.g., after an OS reinstall), stop and tell the user; this requires a
one-time system reconfiguration.

If test results show sequential reads under 100 MB/s, fdatasync completing fewer than 10 IOs in 30
seconds, or latency outliers near 30 seconds, check `dmesg` for `uas_eh_abort_handler`; these are
UAS symptoms, not drive defects.

### Privilege: CAP_SYS_RAWIO

The `disk` group grants block device read/write, but ATA passthrough (SG_IO ioctl) requires
`CAP_SYS_RAWIO`. Without it, smartctl and fio fail with "Operation not permitted" even with correct
group membership. The `disk-diag-caps.path` systemd unit watches both binaries and re-applies
capabilities automatically after package upgrades.

### USB Dock SMART Passthrough

The JMS578 bridge supports ATA passthrough but requires `-d sat` explicitly:

```bash
smartctl -a -d sat /dev/sdX
```

Without `-d sat`, smartctl detects the bridge as SCSI and returns empty/missing SMART data. The `-d
scsi` mode returns the bridge controller's identity (shows "SABRENT"), not the drive. Do NOT use `-d
usbjmicron`; that is for older JMicron chips (JM20329/JM20336).

### USB Dock Sector Size Translation

The JMS578 has a known firmware issue translating 512e drives to 4Kn. This affects capacity
reporting and alignment but does not affect diagnostic reads. Performance numbers over USB are
bottlenecked by USB 3.0 (~430 MB/s sequential ceiling); do not judge throughput specs over USB.

### fio Cache Warnings

Running fio on `/dev/sdX` produces two harmless warnings:

```txt
fio: only root may flush block devices. Cache flush bypassed!
fio: cache invalidation of /dev/sdX failed: Permission denied
```

These do not affect test validity for diagnostic purposes. Direct I/O (`--direct=1`) bypasses the
page cache anyway.

## Command Reference

### Device Discovery

```bash
lsblk -d -o NAME,SIZE,MODEL,SERIAL,TRAN,STATE
```

USB-connected drives show `TRAN=usb`. Identify the target device before running any tests.

### SMART Health Check

```bash
# Full SMART report (USB dock)
smartctl -a -d sat /dev/sdX

# Extended SMART with additional logs
smartctl -x -d sat /dev/sdX

# Start short self-test (~1 min for SSDs, ~2 min for HDDs)
smartctl -t short -d sat /dev/sdX

# Start extended self-test (minutes for SSDs, hours for large HDDs)
smartctl -t long -d sat /dev/sdX

# Check self-test results
smartctl -l selftest -d sat /dev/sdX

# Direct SATA (no dock): omit -d sat
smartctl -a /dev/sdX
```

### Key SMART Attributes

**Universal (SSD and HDD):**

- `5` Reallocated_Sector_Ct: must be 0; any nonzero is a red flag
- `187` Reported_Uncorrect: must be 0
- `197` Current_Pending_Sector: must be 0; sectors awaiting reallocation
- `199` CRC_Error_Count: must be 0; indicates cable/interface errors
- `9` Power_On_Hours: context for wear assessment
- `12` Power_Cycle_Count: low count suggests datacenter life

**SSD-specific (Intel DC series):**

- `170/232` Available_Reservd_Space: spare block pool; threshold is 10
- `171` Program_Fail_Count: must be 0
- `172` Erase_Fail_Count: must be 0
- `233` Media_Wearout_Indicator: 0 = fresh, increases toward 100 (failure)
- `226` Workld_Media_Wear_Indic: Intel's internal wear metric
- `234` Thermal_Throttle: event count; nonzero means thermal issues

**HDD-specific:**

- `10` Spin_Retry_Count: must be 0
- `196` Reallocated_Event_Count: reallocation attempts
- `198` Offline_Uncorrectable: bad sectors found during offline scan

### Performance Tests (fio)

```bash
# Sequential read (throughput ceiling)
fio --name=seq-read --filename=/dev/sdX --rw=read --bs=1M \
    --ioengine=libaio --iodepth=32 --direct=1 --size=4G \
    --runtime=30 --time_based --readonly

# Sequential write
fio --name=seq-write --filename=/dev/sdX --rw=write --bs=1M \
    --ioengine=libaio --iodepth=32 --direct=1 --size=4G \
    --runtime=30 --time_based

# Random 4K read IOPS
fio --name=rand-read-4k --filename=/dev/sdX --rw=randread --bs=4k \
    --ioengine=libaio --iodepth=32 --direct=1 --size=1G \
    --runtime=30 --time_based --readonly

# Random 4K write IOPS
fio --name=rand-write-4k --filename=/dev/sdX --rw=randwrite --bs=4k \
    --ioengine=libaio --iodepth=32 --direct=1 --size=1G \
    --runtime=30 --time_based

# Sync write latency (etcd WAL fsync pattern; most important for Talos drives)
fio --name=sync-write-4k --filename=/dev/sdX --rw=randwrite --bs=4k \
    --ioengine=sync --fdatasync=1 --iodepth=1 --direct=1 --size=512M \
    --runtime=30 --time_based
```

The fdatasync test is the single most important test for etcd/Talos system drives. etcd warns at
10ms WAL fsync p99; good enterprise SSDs should be well under 1ms. Over USB (even with BOT mode),
expect ~10ms of bridge overhead on p99; a drive showing p50 under 0.5ms and p99 under 15ms over USB
is healthy and will be well under 1ms p99 on native SATA.

### Surface Scan (HDD or suspect SSD)

```bash
# Read-only surface scan (non-destructive)
badblocks -sv -b 4096 /dev/sdX

# Read-write destructive test (DESTROYS DATA)
badblocks -wsv -b 4096 /dev/sdX
```

`badblocks` is slow on large drives (hours). For SSDs, SMART self-tests are generally sufficient;
use badblocks only if SMART attributes are suspicious.

## Assessment Framework

When reporting results, evaluate:

1. **Health**: SMART overall status, error counters (all must be zero)
2. **Wear**: media wearout, write endurance consumed vs rated, power-on hours
3. **Performance**: compare against drive's rated specs (discount USB overhead)
4. **Consistency**: latency percentiles (p99, p99.9); spikes indicate dying cells or firmware bugs
5. **Verdict**: keep, return, or test further (with reasoning)

## Rules

- MUST run `lsblk` first to identify the target device; never assume `/dev/sdX`
- MUST NOT write to a drive without explicit user confirmation
- MUST check `getcap` before assuming smartctl/fio have the needed capabilities
- MUST note when USB bottleneck affects results vs native SATA expectations
- MUST NOT run badblocks destructive mode without explicit user confirmation
- Report raw numbers with context (rated specs, USB ceiling, etcd thresholds)
