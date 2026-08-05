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

## Preflight

Verify `smartctl`, `fio`, and `badblocks`, membership in the `disk` group, and the required
`CAP_SYS_RAWIO` capabilities. If a USB drive is attached through the JMS578 dock, confirm it uses
`usb-storage` rather than `uas`. Stop when a prerequisite fails; do not compensate with privilege
escalation.

## Workflow

1. Identify the device, transport, model, serial, size, and current state.
2. Read SMART data and self-test history before running performance tests.
3. Select read-only tests unless writes were explicitly approved.
4. Interpret results in the context of SSD versus HDD and USB versus native SATA.
5. Report health, wear, performance, consistency, and a keep, return, or test-further verdict.

Treat 30-second stalls, failed cache flushes, and `uas_eh_abort_handler` messages through the
JMS578 dock as bridge symptoms until native or BOT-mode testing disproves that explanation.
