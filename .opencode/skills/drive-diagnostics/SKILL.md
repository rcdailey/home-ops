---
name: drive-diagnostics
description: >-
  Use when testing, benchmarking, or assessing SSDs and HDDs; interpreting SMART or fio results;
  running badblocks; working through a USB-to-SATA dock; or invoking `/drive-test`. Do NOT use for
  Kubernetes or Ceph volume performance diagnosis.
---

# Drive diagnostics

Identify the exact device and intended use before selecting tests. Read
`references/testing.md` for commands, thresholds, SMART attributes, and USB dock details.

## Safety

- Run `lsblk` first; never assume a device path.
- Do not write to a drive without explicit user confirmation.
- Do not run destructive badblocks without separate explicit confirmation.
- Run fio tests sequentially over USB.
- Use queue depth 1 for random 4K tests over USB.
- Report raw measurements with the drive specification, connection limit, and use-case threshold.
- Leave RAID, LVM, or filesystem metadata the host activates on attach untouched: do not mount,
  assemble, or stop it. Read-only tests work while the host holds inactive arrays.

## Preflight

Verify `smartctl`, `fio`, and `badblocks`, membership in the `disk` group, and the required
`CAP_SYS_RAWIO` capabilities. Restore missing capabilities through the capability service in
`references/testing.md`; that is the only permitted privilege escalation. If a USB drive is attached
through the JMS578 dock, confirm it uses `usb-storage` rather than `uas`. Stop when any other
prerequisite fails.

## Workflow

1. Identify the device, transport, model, serial, size, and current state.
2. Read SMART data and self-test history before running performance tests.
3. Select read-only tests unless writes were explicitly approved.
4. Over USB, run full-surface checks as the long read scan in `references/testing.md`, not an
   extended self-test; enclosures reset or sleep the drive and the host aborts the self-test.
   Monitor temperature during any scan longer than an hour.
5. Interpret results in the context of SSD versus HDD and USB versus native SATA.
6. Report health, wear, performance, consistency, and a verdict per the reference's verdict rules.

Treat 30-second stalls, failed cache flushes, and `uas_eh_abort_handler` messages through the
JMS578 dock as bridge symptoms until native or BOT-mode testing disproves that explanation.
