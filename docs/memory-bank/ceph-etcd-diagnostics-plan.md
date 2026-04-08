# Ceph/etcd Diagnostic Improvements: Resumption Notes

- **Started:** 2026-04-08
- **Status:** Section 1 complete; sections 2-6 pending
- **Trigger:** [ceph-mon-quorum-loss-etcd-slowness-2026-04-08][investigation]

## Context

Recurring incident pattern: Kubernetes API write slowness correlates with Ceph mon quorum
loss. Investigation paused because diagnostic visibility is insufficient to make another
incident window productive. Rather than guess at root cause, the plan is to land diagnostic
improvements in small sequential PRs so the next incident lands in a fully instrumented
cluster.

Working agreement: one section at a time, implement as we discuss, don't commit without
explicit request.

## Section 1: Ceph log shipping (COMPLETE)

Scope grew substantially during implementation. Final shape:

**Collection pipeline:**

- Vector DaemonSet re-enabled with label-gated opt-in collection via
  `extra_label_selector: observability.home-ops/logs=true`. Only pods that opt in ship
  logs, keeping the default cluster-wide blast radius low.
- Rook mon pods labeled via `cephClusterSpec.labels.mon` in
  `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml`. Rook rolls the label to mon
  pods sequentially during reconcile, so full coverage takes roughly an hour after the
  HR applies.
- Label gate key: `observability.home-ops/logs: "true"`.

**Vector sizing:**

- Memory limit bumped from 512Mi to 1Gi in
  `kubernetes/apps/observability/victoria-logs-single/helmrelease.yaml`. Steady-state
  memory is only 18-21Mi; the 1Gi ceiling absorbs the startup hump (checkpoint catch-up
  - file_server init) that was OOMKilling Vector on the three CP nodes hosting Ceph
  mons. Limit caps but does not reserve, so steady-state cost is unchanged.

**Parsers** (`kubernetes/apps/observability/victoria-logs-single/vrl/`):

- `parse-ceph.vrl`: regex rewritten to consume Ceph's literal `debug` stream-marker
  prefix that the original pattern assumed was absent. The numeric token after the
  thread id is Ceph's dout *verbosity* level, not a syslog severity, so it is captured
  as `.ceph_verbosity` for debugging and `.level` defaults to `info`. Real severity is
  assigned only when the body matches `log_channel(...) log [ERR]` or `[WRN]` (channel
  forwarder lines that slip past `mon_cluster_log_level: info`).
- `parse-default.vrl`: latent VRL bug fixed (the old
  `.kubernetes = del(.kubernetes.pod_labels)` line partially clobbered the kubernetes
  struct because it assigned the deleted value back as a statement).
- Both parsers strip per-event metadata bloat (`pod_labels`, `node_labels`,
  `namespace_labels`, `pod_annotations`, `pod_ips`, `container_image_id`). This was
  the real cause of the Vector OOM loop: each mon event was carrying 100+ NFD
  `feature.node.kubernetes.io/*` labels plus other cluster metadata, inflating per-event
  memory roughly 10x. Raw volume is trivial (roughly 1.5 lines/sec across 3 mons).
- Identity fields preserved: `.app`, `.namespace`, `.ceph_daemon_id`,
  `.ceph_daemon_type`.

**Noise suppression (source-level Ceph config in
`kubernetes/apps/rook-ceph/cluster/helmrelease.yaml` `cephConfig.global`):**

- `mon_cluster_log_level: info`. Silences the `cluster`/`audit` channel forwarder's
  DBG-level lines at the source. Governs both channels with a single knob; Squid
  removed the per-channel level options.
- `debug_rocksdb: 1/5`. Drops store.db SST deletion and compaction chatter (default
  is `4/5`, emitting every file-delete event from the mon's store).
- `mon_cluster_log_to_stderr: "false"`. Disables the LogMonitor's cluster-log stderr
  forwarder entirely. Rook starts mon daemons with
  `--default-mon-cluster-log-to-stderr=true` in cmdline args (see
  `rook/pkg/operator/ceph/config/defaults.go`), which caused every cluster/audit
  channel entry to be written to stderr in a second format (`cluster <ts> mon.X ...`
  / `audit <ts> ...`) on top of the dout trace. In observed logs this forwarder also
  exhibited exact-duplicate pairs for the same log entry with identical microsecond
  timestamps and sequence numbers (roughly 20% of mon stderr lines). Central config
  store overrides the `--default-` cmdline flag at runtime, no mon restart needed.
  Rook's mon health checks use `ceph status` and admin socket commands (verified in
  `rook/pkg/operator/ceph/cluster/mon/health.go`), not log scraping, so removing the
  forwarder output has no operator-side impact. Upstream cephadm recommends the same
  setting (see `ceph/doc/cephadm/operations.rst`, "logged twice").

**Noise suppression (Vector-side):**

- `ceph_noise_filter` transform in
  `kubernetes/apps/observability/victoria-logs-single/vector/vector-transforms.yaml`,
  wired into the vlogs sink via `vector-sinks.yaml`. Drops events whose body contains
  `log_channel(audit) log [DBG]`. These dout traces of the channel dispatch cannot be
  suppressed via Ceph config because they are emitted at dout(0) inside
  `LogChannel::do_log()` before the channel threshold is checked (confirmed via Ceph
  v0.48.1 changelog via Context7). Rook polls the mon admin socket continuously for
  `mon_status`, `osd dump`, `mgr stat`, and `fs dump`, each generating two of these
  traces (`dispatch` and `finished`), so without the filter they dominate the stream.

**Removed:**

- Obsolete per-app VRL parsers (`parse-kometa.vrl`, `parse-qbittorrent.vrl`,
  `parse-cloudflare-tunnel.vrl`) in favor of the enriched default parser.

**Verified end-to-end (steady state, post all fixes):**

- All 5 Vector pods stable on all 5 nodes, zero restarts on CP nodes.
- `KubePodCrashLooping` and `KubeDaemonSetRolloutStuck` alerts cleared.
- All 3 mons (j, m, o) confirm `mon_cluster_log_to_stderr: false` at the daemon
  runtime level via admin socket (`ceph daemon mon.X config show`); no mon restart
  was required for the config change to propagate.
- `kubectl logs -c mon` on all 3 mons shows only `debug <ts>...` prefix lines. No
  `cluster <ts>...` / `audit <ts>...` forwarder lines, no exact-duplicate pairs.
- VictoriaLogs shows `rook-ceph-mon` events from all 3 mons with populated identity
  fields (`.app`, `.namespace`, `.ceph_daemon_id`, `.ceph_daemon_type`,
  `.ceph_verbosity`, `.thread_id`) and all bloat fields stripped. Parser regex
  matches 100% of shipped events; no fall-through to the raw-message path.
- `log_channel(audit) log [DBG]` and rocksdb compaction lines: 0 hits in VL.
- Steady-state volume across all 3 mons: roughly 0.85 events/sec (~51/min), down
  from 1.5/sec pre-parser-fix and 3.2/sec during the transient dual-format phase.
- Level distribution: effectively 100% `info`. The dout→severity mapping was
  removed because Ceph's dout numeric is debug *verbosity*, not syslog severity;
  real severity now only comes from `log_channel(...) log [ERR]` / `[WRN]` body
  pattern overrides in `parse-ceph.vrl`.

**Remaining housekeeping (low priority, not blocking Section 2):**

- `test-samples-ceph.json` still uses a daemon-log format that does not match
  production mon stderr. Refresh the fixtures to the real `debug <ts> <thread>
  <verbosity> <body>` format so future VRL edits can be validated end-to-end via
  `scripts/test-vector/`. This was valuable earlier in Section 1 when the parser
  regex was wrong, and will be valuable again when Section 4 raises debug verbosity
  and changes the expected traffic mix.

## Section 2: etcd metrics re-enable

**Goal:** Restore scraping of etcd internals so the next incident window has
`etcd_disk_wal_fsync_duration_seconds`, `etcd_server_leader_changes_seen_total`,
`etcd_network_peer_round_trip_time_seconds`, and proposal backlog metrics. Current
investigation is bottlenecked on apiserver-side proxies (`etcd_request_duration_seconds_*`)
that only show symptoms.

**Current state (verified):**

- Talos already exposes etcd metrics on `0.0.0.0:2381` via
  `talos/machineconfig.yaml.j2:185` (`listen-metrics-urls`). Patch was never reverted.
- Chart-side scraping was disabled in commit `a70082d` (2025-11-23) because the default
  etcd alert thresholds (150ms) fired constantly on homelab hardware that runs at
  180-200ms normally. Reason was alert noise, not metrics cost.
- `kubeEtcd.enabled: false` and `defaultRules.groups.etcd.create: false` in
  `victoria-metrics-k8s-stack/helmrelease.yaml`.

**Work:**

1. Re-enable `kubeEtcd` scraping (copy working endpoint config from `712b116`).
2. Keep `defaultRules.groups.etcd.create: false` so noisy alerts stay off.
3. Write a custom VMRule with tuned thresholds appropriate for this cluster
   (probably 500ms p99 warn, 2s critical; needs a calibration pass against recent
   data before settling on numbers).
4. Add a minimal Grafana dashboard for etcd internals (fsync, commit, peer RTT,
   leader changes, DB size). Probably import an existing open-source dashboard and
   trim rather than write from scratch.

**Open questions:**

- What are realistic alert thresholds? Need to query `./scripts/query-vm.py` against a
  week of data once scraping is live, then pick thresholds at p99 + headroom.
- Do we want to alert at all in phase 1, or just collect metrics silently and revisit
  alerting after we have a baseline?

## Section 3: Ceph metrics (paxos perf dump + namespace unblock)

**Goal:** Stop being blind to Ceph-internal performance counters that matter for mon
diagnosis (`paxos.begin_latency`, `paxos.commit_latency`, `paxos.collect_latency`,
`mon.election_call`, `mon.num_elections`).

**Current state (verified):**

- `vmagent.serviceScrapeNamespaceSelector` in
  `victoria-metrics-k8s-stack/helmrelease.yaml` only allows
  `[media, default, home, observability]`. The `rook-ceph` namespace is excluded, so
  the chart-generated `VMServiceScrape`/`VMPodScrape` resources have no effect.
- Rook ceph cluster HelmRelease has `monitoring.enabled: true` (line 27), which
  creates scrape resources, but they're not picked up.
- Standard Ceph exporter (`ceph_exporter`) does NOT expose `paxos.*` perf counters.
  Those only come from `ceph daemon mon.X perf dump`.

**Work:**

**Part A (trivial):** Add `rook-ceph` to `vmagent.serviceScrapeNamespaceSelector` and
`podScrapeNamespaceSelector`. This unblocks all standard Ceph metrics. One-line change.

**Part B (custom):** CronJob that runs `ceph tell mon.* perf dump`, parses relevant
counters, writes to node_exporter textfile collector or pushes to VL-as-metrics. Needs
research pass first:

- Does Rook's `ceph_exporter` upstream have a flag to enable paxos counters? Research
  said no, but needs verification against the exporter source.
- Is there a cleaner metrics-push target than textfile? VictoriaMetrics supports
  pushgateway-style ingest via `-enableTCP` on vmagent.
- Where does the CronJob live? Probably
  `kubernetes/apps/rook-ceph/cluster/` as `ceph-perf-collector-cronjob.yaml`.

**Part C (related):** Periodic capture of `ceph daemon mon.X dump_historic_ops` and
`ops` to VL. Low-cost, lets us retroactively ask "what was mon.j doing at 03:08:19 last
Tuesday." Same CronJob as Part B, different subcommand.

## Section 4: Ceph debug logging levels

**Goal:** Have enough log verbosity for post-incident analysis without paying a
constant write tax.

**Approach (from researcher):**

- Always-on: `debug_mon=1/5`, `debug_paxos=1/5`, `debug_ms=1/5`, `debug_rocksdb=1/5`.
  The `1/5` syntax means log-level 1, in-memory ring-buffer level 5. Ring buffer gets
  dumped on crash/assertion but doesn't hit disk during normal operation.
- Incident-window: `ceph tell mon.* config set debug_paxos 10/20` etc. Runtime toggle,
  no restart. Revert after the window closes.

**Work:**

1. Add `cephConfig.global.debug_*` keys to `rook-ceph/cluster/helmrelease.yaml`.
2. Document the incident-window toggle commands somewhere findable (probably
   `docs/runbooks/ceph-incident-response.md`, doesn't exist yet).

**Constraint:** This depends on section 1 being deployed so the log volume has a
pipeline to flow through. Level `1/5` should produce modest volume (MBs/hour), manageable
under the VL retention policy.

## Section 5: Hardware and kernel diagnostics

**Goal:** Rule out slow/dying hardware and detect kernel-level pauses that could cause
coincident etcd + Ceph mon disturbance.

**Candidates with confidence:**

- **PSI metrics** (`/proc/pressure/{cpu,memory,io}`). node_exporter has
  `--collector.pressure`. Verify if already enabled in current values; if not, one-line
  fix. These expose "time spent stalled" which is exactly what we'd expect to see if
  the coincident etcd + Ceph disturbance is kernel-level resource contention.
- **dmesg shipping to VictoriaLogs.** This is the biggest hardware-diagnostic win. The
  2026-04-08 incident timeline was reconstructed by hand from `talosctl dmesg`; it
  should be automatic. Captures: PCIe AER errors, NVMe controller resets, MCE/ECC
  errors, libceph kernel client errors, etcd Talos health-check failures. Approach:
  Vector `file` source tailing host `/var/log/kern.log` (need to verify Talos path),
  or `exec` source running `talosctl dmesg --follow`. Research needed.
- **Kernel boot args** for `hung_task_timeout_secs` and `rcutree.rcu_cpu_stall_timeout`.
  Investigation noted "no kernel hung-task or RCU-stall messages" so detectors are
  active but may need tuning. Talos machine config kernel.args field.
- **NVMe SMART via sysfs.** `/sys/class/nvme/nvme*/` exposes some counters without
  smartmontools. Textfile collector CronJob writes Prometheus exposition. Needs a pass
  to map which sysfs paths actually exist on Talos.

**Candidates flagged as researcher fantasy:**

- "Talos Prometheus operator extension" (claimed by researcher, I don't believe it
  exists as described).
- Always-on ftrace/eBPF (too expensive).
- Remote memtest (not a thing on running systems).

**Work:**

1. Verify `--collector.pressure` state in current node-exporter values.
2. Prototype dmesg shipping via Vector `exec` source wrapping `talosctl dmesg --follow`.
   Figure out auth/kubeconfig-equivalent for reaching Talos API from inside a pod.
3. Write a textfile-collector CronJob for NVMe sysfs counters. Needs a discovery pass
   on an actual node first.
4. Kernel args: `talos/machineconfig.yaml.j2` edit, requires `just talos apply-node`
   sequentially per control plane node.

## Section 6: Single-pane-of-glass investigation dashboard

**Goal:** When the next incident fires, have one place to open that shows the whole
picture: etcd internals, apiserver latency, Ceph mon status, kernel PSI, recent
dmesg/ceph logs. User explicitly asked for this as a top priority.

**Current state:**

- VictoriaLogs already has a Grafana datasource plugin (standard pattern).
- Metrics and logs already share common labels (`node`, `pod`, `namespace`).

**Work (depends on sections 1-5):**

1. Grafana dashboard: `docs/investigations/templates/incident-overview.json` or inline
   in `kubernetes/apps/observability/grafana/dashboards/`.
2. Top row: etcd fsync p99, apiserver write p99, Ceph mon quorum status (0/1 per mon),
   node PSI full-stall percentages. All time-aligned, 5m step, 24h default range.
3. Bottom row: VL log panel pre-filtered to `rook-ceph` namespace + `level>=warn`,
   and a second panel for kernel dmesg WARN+ from the dmesg stream.
4. Template variable for time range so "zoom to this incident" is one click.

Deferred until real data is flowing; designing a dashboard against empty panels is
pointless.

## Ordering and dependencies

```txt
Section 1 (Ceph logs)     DONE
        |
        v
Section 4 (debug levels)  depends on section 1 (needs log pipeline)
        |
Section 2 (etcd metrics)  independent, can run parallel
Section 3 (Ceph metrics)  independent, can run parallel
Section 5 (hw/kernel)     independent, can run parallel
        |
        v
Section 6 (dashboard)     depends on 2, 3, 5 for useful panels
```

Recommended next: Section 2 (etcd metrics). Highest leverage, smallest blast radius,
unblocks dashboard work, and the Talos-side plumbing is already in place.

## References

- [ceph-mon-quorum-loss-etcd-slowness-2026-04-08.md][investigation]: the source
  investigation that triggered this plan
- Commit `a70082d`: etcd monitoring disable rationale
- Commit `712b116`: original working etcd scrape config (reference for re-enable)
- Commit `ee03386`: Vector DaemonSet disable rationale (opt-in sidecar pattern decision)

[investigation]: /docs/investigations/ceph-mon-quorum-loss-etcd-slowness-2026-04-08.md
