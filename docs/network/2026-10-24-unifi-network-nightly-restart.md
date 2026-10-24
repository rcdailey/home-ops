# UniFi Network app nightly restart on the UDM Pro

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decision:** Restart the UniFi Network app every night at 04:30 from a root cron entry on the
  console.

## Context and Problem Statement

UniFi Network 10.6.106 (UniFi OS 5.1.33) on the UDM Pro leaks memory. The app runs with a fixed 512
MB heap (`-Xmx512M` in `/etc/default/unifi`), and its live set grows until full garbage collections
run back to back and the management UI slows or times out. Packet forwarding is not affected.

Measured on this console from `/data/unifi/logs/gc.log`: the post-full-GC heap was 150 MB nine
minutes after a restart and 343 MB after 16 days, about 12 MB per day. At 16 days a full GC ran
every 30 to 40 seconds with pauses of about 0.65 seconds. A restart at that point took 57 seconds
because `unifi.service` exceeded its 30 second stop timeout and was killed.

The [leak thread][leak-thread] reports the same pattern on a UDM SE (about 25 MB per day) and no fix
appears in the [10.6.106 release notes][release-notes].

## Considered Options

- **Scheduled restart** - cron entry that restarts `unifi` daily.
- **Larger heap** - raise `-Xmx` in `/etc/default/unifi`, as in the
  [failed-to-start thread][heap-thread]. This only delays the failure, and the file belongs to the
  `udmpro-al324-base-files` package, so firmware updates replace it.
- **Infrastructure as code** - Ansible over SSH could manage the file, but one console file did not
  justify a new toolchain.

## Decision Outcome

Chosen option: **Scheduled restart**, because it bounds heap growth to one day regardless of the
leak rate and survives reboots.

`/etc/cron.d/unifi-restart` contains:

```txt
30 4 * * * root /bin/systemctl restart unifi
```

The path must be `/bin/systemctl`; `/usr/bin/systemctl` does not exist on the console and cron fails
silently. 04:30 avoids the console's own schedule (times in America/Chicago):

| Job                               | Schedule               |
| --------------------------------- | ---------------------- |
| Network app autobackup            | 00:30 on the 1st       |
| `uos system prune`                | Saturday 00:15         |
| Radio AI                          | Daily 03:00            |
| `e2scrub_all`                     | Sunday ~03:10          |
| UniFi OS and Network auto-update  | Sunday 05:00           |
| `systemd-tmpfiles-clean`          | Daily ~05:50           |
| `apt-daily-upgrade`               | Daily ~06:00 to 06:30  |
| Device firmware auto-upgrade      | Daily 07:00            |
| Speed test                        | Daily 08:00            |

Auto-update times are set in Network, Settings, Updates. If they move, keep at least 30 minutes
between them and the restart.

## Consequences

- Good, because the heap returns to its baseline every night.
- Bad, because the management UI and controller are unavailable for up to about a minute each night.
- Bad, because persistence across firmware updates is unofficial. The root filesystem is an overlay
  on `/mnt/.rwfs/data`, which keeps the file across reboots, and the leak thread reports it survived
  5.1.19 to 5.1.26.

## Verification and Revert

After each firmware update, confirm the file exists:

```sh
./scripts/unifi-ssh.sh 192.168.1.1 cat /etc/cron.d/unifi-restart
```

After 04:30, confirm the restart ran:

```sh
./scripts/unifi-ssh.sh -f 'Stopping|Started' 192.168.1.1 journalctl -u unifi --since today
```

Remove the entry when a Network release fixes the leak:

```sh
./scripts/unifi-ssh.sh 192.168.1.1 rm /etc/cron.d/unifi-restart
```

## References

- [UDM-SE UniFi Network leaks ~25 MB/day, GC death spiral][leak-thread]
- [UDM SE 10.6.106 failed to start Network][heap-thread]
- [UniFi Network Application 10.6.106 release notes][release-notes]

[leak-thread]: https://community.ui.com/questions/19a10247-6b99-4715-8fc5-3f54a84e9741
[heap-thread]: https://community.ui.com/questions/Solved-UDM-Pro-SE-10-6-106-failed-to-start-Network/dd7d68d1-6bbe-4dfe-a68a-d417efd72b9b
[release-notes]: https://community.ui.com/releases/UniFi-Network-Application-10-6-106/f206c01d-3f73-471b-b4a5-2da48f157ea6
