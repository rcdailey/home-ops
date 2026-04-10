# Ceph/etcd Diagnostic Improvements: Resumption Notes

- **Started:** 2026-04-08
- **Status:** Sections 1-6 complete
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
- `talos_noise_filter` transform (same file), wired between `talos_parser` and the
  vlogs sink. Drops Talos machined gRPC access logs (`machined OK
  [/machine.MachineService/...]` and `machined/authz/authorizer authorized`) that
  Prometheus metric scraping generates at ~1.2k/min. These can't be suppressed at
  the Talos source (no gRPC access log filtering knob). etcd health check failures,
  kernel messages, and other service logs pass through unaffected.

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

## Section 2: etcd metrics re-enable (COMPLETE, alerting deferred)

**Goal:** Restore scraping of etcd internals so the next incident window has
`etcd_disk_wal_fsync_duration_seconds`, `etcd_server_leader_changes_seen_total`,
`etcd_network_peer_round_trip_time_seconds`, and proposal backlog metrics.

**Completed:**

- Re-enabled `kubeEtcd` scraping in `victoria-metrics-k8s-stack/helmrelease.yaml`
  using the proven config from commit `712b116` (Service selector
  `component: kube-apiserver` on port 2381, HTTP scheme).
- Default etcd alert rules remain off (`defaultRules.groups.etcd.create: false`).
- Verified: 141 etcd metrics flowing from all 3 CP nodes (hanekawa, marin, sakura).
  All four target metric families confirmed present: `etcd_disk_wal_fsync_*`,
  `etcd_server_leader_changes_seen_total`, `etcd_network_peer_round_trip_time_*`,
  `etcd_server_proposals_*`.

**Deferred (needs ~1 week of baseline data):**

- Custom VMRule with tuned thresholds. Calibration query once data accumulates:
  `./scripts/query-vm.py query 'histogram_quantile(0.99,
  rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m]))' --from 7d`
- Grafana dashboard for etcd internals (folded into Section 6).

## Section 3: Ceph metrics (COMPLETE Part A; Parts B/C pending)

**Goal:** Stop being blind to Ceph-internal performance counters that matter for mon
diagnosis (`paxos.begin_latency`, `paxos.commit_latency`, `paxos.collect_latency`,
`mon.election_call`, `mon.num_elections`).

**Part A (COMPLETE):**

- Added `rook-ceph` to `vmagent.serviceScrapeNamespaceSelector` and
  `podScrapeNamespaceSelector` in `victoria-metrics-k8s-stack/helmrelease.yaml`.
  Rook already had `monitoring.enabled: true` creating ServiceMonitor/PodMonitor
  resources; the VM operator converts these to VMServiceScrape/VMPodScrape. They
  were just being ignored because the namespace wasn't allowlisted.
- Raised CephPGImbalance alert threshold from 30% to 50% via
  `prometheusRuleOverrides` in `rook-ceph/cluster/helmrelease.yaml`. The default
  fires constantly with mixed-size OSDs (2x 1.8TiB + 3x 932GiB) because larger
  OSDs get proportionally more PGs by design.

**Part B (pending, needs research):** CronJob for `ceph tell mon.* perf dump` to
expose paxos counters not available through the standard exporter. Open questions:

- Does Rook's `ceph_exporter` upstream have a flag to enable paxos counters?
- Cleaner push target than textfile? VictoriaMetrics supports pushgateway-style
  ingest via `-enableTCP` on vmagent.
- CronJob location: probably `kubernetes/apps/rook-ceph/cluster/`.

**Part C (pending):** Periodic capture of `ceph daemon mon.X dump_historic_ops` to
VictoriaLogs. Same CronJob as Part B, different subcommand.

## Section 4: Ceph debug logging levels (COMPLETE)

**Goal:** Have enough log verbosity for post-incident analysis without paying a
constant write tax.

**Completed:**

- Added `debug_mon: 1/5`, `debug_paxos: 1/5` to `cephConfig.global` in
  `rook-ceph/cluster/helmrelease.yaml` (alongside the existing
  `debug_rocksdb: 1/5` from Section 1).
- `debug_ms` changed from `1/5` to `0/5`. Verbosity 1 generated ~5k lines/min
  of messenger chatter (paxos leases, mgr beacons, route forwarding) that wrote
  to the Talos system disk via containerd log capture, counterproductive when
  investigating write contention. Verbosity 0 still emits connection errors and
  state changes. The in-memory ring buffer (level 5) preserves full detail for
  crash dumps.
- The `X/Y` syntax is verbosity (not severity): X is verbosity written to disk
  (stderr), Y is verbosity held in the in-memory ring buffer. Higher number = more
  verbose. The ring buffer dumps on crash/assertion, giving detailed context around
  failures without constant disk cost.
- These propagate via Ceph's central config store at runtime; no mon restart needed.

**Incident-window toggle** (runtime, no restart, revert after):

```bash
ceph tell mon.* config set debug_paxos 10/20
ceph tell mon.* config set debug_mon 10/20
ceph tell mon.* config set debug_ms 5/10
```

**Pending:** Document the incident-window toggle commands in a runbook
(`docs/runbooks/ceph-incident-response.md`, doesn't exist yet).

## Section 5: Hardware and kernel diagnostics

**Goal:** Rule out slow/dying hardware and detect kernel-level pauses that could cause
coincident etcd + Ceph mon disturbance.

**Candidates with confidence:**

- **PSI metrics** (`/proc/pressure/{cpu,memory,io}`): ALREADY COLLECTED. Verified
  17 pressure metrics present (`node_pressure_*`, `container_pressure_*`,
  `process_pressure_*`). No work needed.
- **dmesg + Talos service log shipping to VictoriaLogs:** COMPLETE (committed in
  `4d19b4d`). See item 2 below.
- **Kernel boot args** for `hung_task_timeout_secs` and `rcutree.rcu_cpu_stall_timeout`:
  SKIPPED. `CONFIG_DETECT_HUNG_TASK` is not compiled into the Talos 6.18 kernel (no
  `/proc/sys/kernel/hung_task_timeout_secs`). `rcutree.rcu_cpu_stall_timeout` parameter
  was removed in newer kernels; only `csd_lock_suppress_rcu_stall` exists (set to `N`,
  meaning stall warnings are active with defaults). No action needed.
- **NVMe SMART via sysfs:** SKIPPED. Discovery pass confirmed sysfs only exposes
  identity info (model, serial, firmware, state) and hwmon temps; no SMART counters
  (wear, media errors, spare capacity). Getting SMART data requires `nvme-cli` or
  `smartctl`, both needing privileged device access. A Talos system extension
  (`ghcr.io/siderolabs/nvme-cli`) exists but requires a schematic rebuild + Talos
  upgrade + privileged CronJob. Node-exporter already collects the acute indicators
  (IO latency via `node_disk_io_time_seconds_total`, temps via
  `node_hwmon_temp_celsius{chip=nvme_nvme0}`, device state via `node_nvme_info`).
  Deferred as low-value relative to privilege cost.

**Candidates flagged as researcher fantasy:**

- "Talos Prometheus operator extension" (claimed by researcher, I don't believe it
  exists as described).
- Always-on ftrace/eBPF (too expensive).
- Remote memtest (not a thing on running systems).

**Work:**

1. ~~Verify `--collector.pressure` state in current node-exporter values.~~ Done,
   already collected.
2. ~~Prototype dmesg shipping.~~ COMPLETE (committed in `4d19b4d`). See details below.
3. ~~NVMe sysfs counters.~~ SKIPPED (see candidates above).
4. ~~Kernel args.~~ SKIPPED (see candidates above).

### Item 2: Talos log shipping (COMPLETE, committed in 4d19b4d)

**Approach (changed from original plan):** Talos has no persistent log files on disk
(immutable/ephemeral filesystem). The `exec` source wrapping `talosctl dmesg --follow`
would have required Talos API credentials inside a pod. Instead, Talos's native log
push was used: `machine.logging.destinations` (service logs) and `KmsgLogConfig`
(kernel dmesg) both push JSON Lines over TCP. Both apply via `just talos apply-node`
with no Talos upgrade needed. The original plan mentioned a kernel arg
(`talos.logging.kernel`) which would have required a schematic rebuild + Talos
upgrade; `KmsgLogConfig` (a machine config document type) avoids that entirely.

**Vector pipeline (6 files changed in
`kubernetes/apps/observability/victoria-logs-single/`):**

- `vector-sources.yaml`: Added `talos` socket source (TCP :6170, JSON decoding).
- `vector-transforms.yaml`: Added `talos_enrich` (injects `spec.nodeName` via env
  var, expanded at Vector startup) and `talos_parser` (VRL file).
- `vector-sinks.yaml`: Wired `talos_parser` into vlogs sink; added `node` to
  VL-Stream-Fields (one field per line using `>-` folded scalar). Existing k8s logs
  don't set `.node` so existing streams are unaffected.
- `vrl/parse-talos.vrl`: Normalizes both service logs (`talos-level`, `talos-service`,
  `talos-time`) and kernel messages (`priority`, `facility`, `seq`). Service logs get
  `.app` = service name; kernel logs get `.app = "kernel"` + `.kernel_facility`.
  Monotonic `clock` dropped (useless without boot-time correlation). `caller` cleaned.
- `kustomization.yaml`: Added `parse-talos.vrl` to VRL configMapGenerator.
- `helmrelease.yaml`: Added `podHostNetwork: true` (so Talos can push to
  `localhost:6170`), TCP containerPort 6170, `VECTOR_NODE_NAME` env var via downward
  API (`fieldRef: spec.nodeName`).

**Talos machine config (`talos/machineconfig.yaml.j2`):**

- `machine.logging.destinations`: `tcp://127.0.0.1:6170/`, `json_lines` format.
  Ships Talos service logs (machined, apid, etcd, kubelet health checks).
- `KmsgLogConfig` document: `tcp://127.0.0.1:6170/`. Ships kernel ring buffer
  (dmesg). Same TCP endpoint, different document type.

**VRL test harness refactored (`scripts/test-vrl.py`):**

The old `scripts/test-vector/` harness required modifying 4 files per new parser
(docker-compose mount, source, sink, test data). Replaced with a convention-based
runner:

- Drop `vrl/tests/<parser-name>.json` matching `vrl/<parser-name>.vrl`.
- `test-vrl.py` discovers fixtures by glob, runs each through a minimal Vector
  pipeline (`stdin -> remap(vrl) -> console`), does subset field comparison against
  expected output.
- Zero harness files to modify for new parsers.
- Existing test fixtures moved: `test-samples.json` -> `tests/parse-default.json`,
  `test-samples-ceph.json` -> `tests/parse-ceph.json`.
- `tests/parse-talos.json`: 10 test cases covering service logs, kernel messages,
  hybrid events, unknown source fallback, and metadata cleanup.
- parse-ceph and parse-default have pre-existing fixture staleness (6 failures).
  These predate this work; the fixtures reference `ceph_level` and timestamp
  formats that were changed in Section 1.
- The old full-pipeline harness (`scripts/test-vector/`) was also updated to mount
  `parse-talos.vrl` and wire `talos_parser` into its sink. It still works for
  integration smoke tests.

**Deployment sequence (after commit/push):**

1. Flux deploys updated Vector DaemonSet (hostNetwork + socket listener).
2. `just talos apply-node <node>` sequentially on all 5 nodes activates log push.
3. Verify in VictoriaLogs: service logs (`app=machined`, `app=etcd`, etc.) and
   kernel messages (`app=kernel`) with per-node `node` field.

**Open question:** Talos reconnects if Vector restarts, but during Vector downtime
(pod restart, node drain) logs are dropped. Talos doesn't buffer. For the diagnostic
use case (post-incident analysis) this is acceptable; we only lose logs during the
brief restart window, not during the incident itself. If this becomes a problem,
switching from `localhost` to a cluster Service with multiple backends would add
redundancy at the cost of losing per-node routing.

## Section 6: Single-pane-of-glass investigation dashboard

**Goal:** When the next incident fires, have one place to open that shows the whole
picture: etcd internals, apiserver latency, Ceph mon status, kernel PSI, recent
dmesg/ceph logs. User explicitly asked for this as a top priority.

**Current state:**

- VictoriaLogs already has a Grafana datasource plugin (standard pattern).
- Metrics and logs already share common labels (`node`, `pod`, `namespace`).

**Completed:**

Dashboard deployed as `ceph-etcd-incident-overview` in
`kubernetes/apps/observability/grafana/dashboards/`. Uses GrafanaDashboard CR with
datasource variable mapping for both VictoriaMetrics (metrics) and VictoriaLogs
(logs).

**Layout (4 rows, 11 panels):**

- **Cluster Health:** etcd WAL fsync p99 (with 10ms/50ms thresholds), apiserver
  mutating request p99, Ceph mon quorum status (0/1 per mon)
- **etcd Internals:** leader change rate (bar chart for spikes), proposals pending,
  peer round-trip p99 (with 50ms/100ms thresholds)
- **Resource Pressure (PSI):** CPU waiting %, memory full-stall %, I/O full-stall %
  (all per-node via `node_uname_info` join for hostname legends)
- **Logs:** Ceph warn+ from VictoriaLogs (`{namespace="rook-ceph"} AND
  (level:warning OR level:warn OR level:error OR level:critical)`), kernel dmesg
  (`{app="kernel"}`)

All panels share crosshair tooltip (`graphTooltip: 2`) for time-aligned correlation.
Default time range is 24h. Grafana's native time picker provides zoom-to-incident.

## Ordering and dependencies

```txt
Section 1 (Ceph logs)     DONE
Section 2 (etcd metrics)  DONE (scraping live; alerting deferred ~1 week for baseline)
Section 3 (Ceph metrics)  Part A DONE; Parts B/C pending research
Section 4 (debug levels)  DONE
Section 5 (hw/kernel)     DONE (items 1-2 complete; items 3-4 skipped, see notes)
Section 6 (dashboard)     DONE
```

## References

- [ceph-mon-quorum-loss-etcd-slowness-2026-04-08.md][investigation]: the source
  investigation that triggered this plan
- Commit `a70082d`: etcd monitoring disable rationale
- Commit `712b116`: original working etcd scrape config (reference for re-enable)
- Commit `ee03386`: Vector DaemonSet disable rationale (opt-in sidecar pattern decision)

[investigation]: /docs/investigations/ceph-mon-quorum-loss-etcd-slowness-2026-04-08.md
