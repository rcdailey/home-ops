# Node logging cleanup and collector evaluation

- **Date:** 2026-08-23
- **Status:** UNRESOLVED

## Summary

The node logging pipeline retains Ceph and Talos diagnostics created for an April 2026 incident
that was later attributed to the nodes' former system drives. Those sources now account for most
of the stored logs without a current dashboard, alert, or other repository consumer. Kubernetes
API audit logs remain useful for tracing client certificate alerts, but the broad audit policy can
exclude service accounts without losing certificate-authenticated clients.

This plan removes stale sources and processing before choosing whether to replace the bundled
Vector DaemonSet with VictoriaLogs Collector (`vlagent`). The collector decision is intentionally
deferred until the reduced workload is measured.

## Symptoms

The current Vector DaemonSet stores about 60.5 million events per day:

| Source | Events per day | Share |
| --- | ---: | ---: |
| Talos services and kernel | 53.45 million | 88.4% |
| Kubernetes API audit | 4.41 million | 7.3% |
| Selected pod logs | 2.63 million | 4.3% |
| Ceph mons, included above | 142 thousand | 0.2% |

Talos `auditd` produces 49.66 million events per day. Samples are repeated SELinux AVC and syscall
records, including denied writes from `victoria-metrics-prod` to an RBD directory labeled
`unlabeled_t`. Nami produces 34.68 million of these records. SELinux is permissive, but the event
rate indicates a source problem that should be corrected rather than hidden with a collector
filter.

The API audit policy records `Metadata` for every request. About 3.21 million of 4.41 million daily
events, or 73%, authenticate as `system:serviceaccount:*`. Service accounts use bearer tokens, not
the client certificates measured by the kube-apiserver expiration alert.

## Investigation

### Current responsibilities

The bundled Vector DaemonSet has four responsibilities:

1. Collect pod logs selected by `observability.home-ops/logs=true`.
2. Parse and filter Rook Ceph mon stderr.
3. Receive Talos service and kernel JSON Lines on each node over TCP port 6170.
4. Tail and parse the kube-apiserver audit file on control-plane nodes.

The Ceph and Talos pipelines were added while investigating coincident Ceph mon quorum loss and
etcd latency. The incident dashboard removed its log panels on 2026-04-13. Later dashboard commits
recorded the former consumer SATA system drives as the cause and repurposed the dashboard after the
drives were replaced. No current dashboard or alert consumes the specialized Ceph or Talos fields.

### Ceph source logging

Ceph debug settings use `<disk level>/<memory level>`. Lowering the first value reduces formatted
and emitted records. Lowering the second reduces what the bounded in-memory crash buffer retains.
The current settings are already conservative:

- `debug_mon: 1/5`, `debug_paxos: 1/5`, and `debug_ms: 0/5` match documented defaults.
- `debug_rocksdb: 1/5` emits less than the documented `4/5` default.
- `mon_cluster_log_to_stderr: false` prevents duplicate cluster-channel forwarding.

Disabling every Ceph logging destination would reduce some daemon CPU, container-runtime writes,
collector work, and VictoriaLogs storage. The expected daemon benefit is small at the observed
142 thousand records per day, and complete disablement would remove local evidence needed for a
future monitor, Paxos, RocksDB, or messenger failure.

The appropriate boundary is to stop central collection while retaining conservative local Ceph
logging. Removing the mon opt-in label eliminates Vector and VictoriaLogs work, but it does not
eliminate Ceph formatting or containerd's local log write.

### Talos logging

Talos remote forwarding has no current repository consumer. It produces 53.45 million records per
day, of which 49.66 million are `auditd` and 3.70 million are `machined`. Only 1,907 records were
warnings and 21 were errors in the measured window.

The original post-incident correlation use case no longer justifies a raw TCP listener, host
networking, a parser, and content filters on every node. Removing the Talos logging destination and
`KmsgLogConfig` also removes the only requirement that `vlagent` cannot ingest directly.

The SELinux audit flood must be investigated before remote forwarding is removed. Otherwise the
cluster would stop exposing the flood centrally while the source continued generating it.

The 2026-08-25 implementation gate found two active source defects. A 24-hour query returned
5.10 million AVC records across all five nodes. The highest-volume patterns in a one-hour sample
were VLSingle writing to RBD (`118,337`), Cilium writing `/run/cilium/state` (`71,131`), and
VMSingle writing to RBD (`14,994`). Lower-volume RBD denials also affected Sonarr and PostgreSQL.

Every sampled RBD denial had the same boundary: a process running as `pod_t:s0` wrote to an ext4
RBD filesystem labeled `unlabeled_t`. The RBD `CSIDriver` advertises `seLinuxMount: true`, but its
node plugin does not mount the host `/etc/selinux`, and the Pods have no explicit SELinux options.
Enabling the ceph-csi host SELinux mount is a supported prerequisite, but it cannot create a mount
label when Kubernetes receives no Pod SELinux options. Kubernetes 1.36 also leaves `SELinuxMount`
disabled by default for ordinary `ReadWriteOnce` claims.[^rbd-selinux]

Talos 1.13.8 currently assigns these containers the static `pod_t:s0` process context. The same
upstream Talos issue reports both unlabeled CSI volumes and Cilium's `/run/cilium` denial. Talos has
no documented generic file type for writable CSI volumes, so a StorageClass-wide static `context=`
mount option or workload `seLinuxOptions.level: s0` would weaken isolation without establishing a
valid RBD label.[^talos-selinux-issue] The source therefore cannot yet be corrected safely in this
repository. Collector removal is blocked until Talos supplies a supported CSI volume-labeling
boundary or upstream confirms a policy-compatible label.

Cilium is a separate host-path policy defect. Talos intends `/run/cilium` to transition from
`run_t` to `pod_containerd_run_t`, while the live directory remains `run_t`. This must be resolved
at the Cilium host-path or Talos policy boundary, not by changing RBD or filtering audit records.

### Kubernetes API audit policy

`Metadata` audit events contain the username, groups, source IPs, user agent, verb, resource,
request URI, timestamps, and response status needed to trace a certificate alert. The policy
cannot match certificate identity or expiration, source IP, user agent, or response status. It can
match users, groups, verbs, resources, namespaces, and non-resource URLs.

A broad catch-all remains necessary while the certificate-authenticated client is unknown. A
first-match `None` rule for the `system:serviceaccounts` group can remove about 73% of current
events without excluding client-certificate authentication. The remaining records include the
API server, controller manager, scheduler, nodes, Talos administrators, and other certificate or
interactive clients.

The policy should retain `omitStages: [RequestReceived]` so each completed request is not
duplicated. Further exclusions require evidence that the excluded identity cannot be the client
behind the expiration alert.

### Plain-text application severity

The default Vector parser currently sets `level=info` whenever an event does not already contain a
structured level. This makes plain-text debug and warning records look informational. A 24-hour
sample found:

| Application | Format | Embedded severity | Observed records |
| --- | --- | --- | ---: |
| External DNS | logfmt | `level=info` | 1,428 info |
| Recyclarr | `[DBG]`, `[INF]`, and related tokens | 789 debug, 33 info, 3 unmatched | 825 |
| SABnzbd | `::LEVEL::` | 368,898 debug; 981,336 info; 316 warning | 1,353,212 |
| qBittorrent | `(I)`, `(N)`, `(W)`, `(C)` tokens | 11,822 `(I)`, 60 `(N)` | 11,882 |
| Paperless Classifier | Python text | No severity in samples | 28 in seven days |

External DNS supports `--log-format=json` and should emit structured records at the source.
Paperless Classifier is maintained in this repository and can also emit JSON directly. Recyclarr
and SABnzbd have stable text formats but no supported JSON console mode. qBittorrent exposes a
structured WebUI log API, but its container console format has no documented JSON option.

`vlagent` cannot materialize severity from these text formats. For the current LLM diagnostic use
case, application-specific LogsQL extraction in `hops` can normalize severity at query time without
adding a second node collector. No current dashboard or alert depends on stored severity for these
applications. If a future alert requires a persisted level, that workload needs structured source
output or an explicitly scoped parsing collector.

Plex remains a separate case. Its sidecar tails private files and correctly extracts timestamp,
level, thread, message, and filename. That requirement should stay workload-scoped when its Vector
sidecar is replaced. The `TooManyLogs` rule uses VictoriaMetrics' internal
`vm_log_messages_total{level="error"}` metric, not application fields stored in VictoriaLogs, so it
does not require ingestion-time parsing for these applications.

### Collector comparison

There is no reliable three-way community consensus. The available discussions support these
recurring views:

- Fluent Bit is the familiar Kubernetes default and has CNCF graduated status. Operators value its
  broad output and parser support, but repeatedly report difficult configuration, rotation edge
  cases, and workload-dependent memory behavior.
- Vector is valued for VRL, routing, documentation, and reliable complex pipelines. Reports about
  resource use conflict, and Kubernetes metadata or high-cardinality workloads can be expensive.
- `vlagent` has the smallest surface for VictoriaLogs and uses its native ingestion protocol. It is
  newer and narrower, with less community history and no general transform or multiline pipeline.

VictoriaMetrics' 2026 benchmark measured `vlagent` below Fluent Bit and Vector for CPU and memory
and above both for throughput. It is vendor-produced evidence and should not substitute for a
measurement on this cluster. Community reports also show that each collector has rotation,
buffering, retry, or overload edge cases.

After this cleanup, the required node pipeline is limited to selected Kubernetes container logs
and JSON Lines audit files. It does not require VRL, arbitrary regex parsing, multiline assembly,
raw TCP, or content routing. That workload fits `vlagent`, but keeping the bundled Vector chart is
also reasonable if a second Helm release and migration provide no measured benefit.

## Root Cause

Diagnostic collection outlived the incident that justified it. The Ceph and Talos paths remained
after the system-drive replacement and after the incident dashboard stopped using their logs.
Vector's flexible transforms then made each source look like a permanent collector requirement.

The current volume is dominated by two separate source problems:

1. Talos forwards every service record, including an SELinux audit flood.
2. The kube-apiserver audit policy records every service-account request even though the immediate
   requirement is attribution of client-certificate alerts.

Changing collectors before removing those sources would preserve the unnecessary volume and make
the migration harder to evaluate.

## Resolution

No cluster changes have been made. Execute the cleanup in the following order.

### Phase 1: correct the SELinux audit flood

1. Identify the volume, mount, and workload associated with each repeating AVC pattern.
2. Determine why the mounted RBD directory is labeled `unlabeled_t`.
3. Correct the source labeling or workload boundary through GitOps.
4. Do not add a Vector, `vlagent`, or VictoriaLogs filter for the repeating AVC records.

Acceptance:

- The repeating `victoria-metric` AVC pattern no longer appears.
- Talos `auditd` volume is measured for another 24-hour window.
- The affected workload and its storage remain healthy.

### Phase 2: stop central Ceph log collection

1. Remove `observability.home-ops/logs=true` from Rook Ceph mons.
2. Remove the Ceph route, parser, noise filter, and parser fixture from Vector.
3. Keep conservative Ceph source logging and `mon_cluster_log_to_stderr: false`.
4. Remove incident-specific Ceph comments that no longer describe a current requirement.

Acceptance:

- No `rook-ceph-mon` records have timestamps newer than the cutover.
- Ceph remains healthy and local pod logs remain available for direct diagnosis.
- Vector no longer loads Ceph metadata or parsing rules.

### Phase 3: remove Talos remote logging

1. Remove `machine.logging.destinations` from the Talos machine configuration.
2. Remove `KmsgLogConfig` for port 6170.
3. Apply the Talos configuration through the repository's normal node workflow.
4. Remove the Vector TCP source, Talos parser, noise filter, fixture, and sink input.
5. Remove host networking and port 6170 when no remaining source requires them.

Acceptance:

- No new `talos-service` or `talos-kernel` records enter VictoriaLogs.
- Talos nodes remain healthy after the configuration rollout.
- Vector exposes no raw TCP listener and does not require host networking.
- Kubernetes container and API audit logs continue to arrive.

### Phase 4: narrow Kubernetes API auditing

1. Measure audit volume and identities immediately before the policy change.
2. Add a first-match `None` rule for `system:serviceaccounts`.
3. Retain a final `Metadata` catch-all and omit `RequestReceived`.
4. Compare event volume, client identities, and certificate-alert evidence after 24 hours.

Proposed policy shape:

```yaml
auditPolicy:
  apiVersion: audit.k8s.io/v1
  kind: Policy
  omitStages:
    - RequestReceived
  rules:
    - level: None
      userGroups:
        - system:serviceaccounts
    - level: Metadata
```

Acceptance:

- Audit volume falls by approximately 70% without changing the final catch-all.
- Events retain `user.username`, `user.groups`, `sourceIPs`, `userAgent`, request metadata, and
  response status.
- Requests authenticated by API server, controller, scheduler, node, admin, and other non-service
  account identities remain queryable.
- Client-certificate alerts can still be correlated with an audit identity and source IP.

### Phase 5: establish the reduced Vector baseline

1. Run the reduced Vector pipeline for at least 24 hours.
2. Record per-node CPU, memory, restart count, delivery errors, and daily event volume.
3. Confirm whether the default parser adds fields beyond what `vlagent` provides.
4. Define `hops` severity extraction for retained plain-text application formats.
5. Confirm the exact `app`, message, timestamp, and stream contracts used by `hops`.

Acceptance:

- The remaining pipeline has only selected pod logs, API audit files, internal metrics, and the
  VictoriaLogs sink.
- No remaining source requires raw TCP, host networking, regex parsing, or content filtering.
- External DNS and Paperless Classifier emit structured JSON.
- `hops` reports normalized severity for retained plain-text formats.
- The baseline is recorded before choosing a collector.

### Phase 6: collector decision gate

Choose between these outcomes after the reduced baseline is available:

1. Keep bundled Vector if its measured cost is small and one Helm release is operationally simpler.
2. Move to VictoriaLogs Collector if native ingestion, disk buffering, and lower measured overhead
   justify a separate release and checkpoint migration.
3. Use Fluent Bit only if testing exposes a required parser or compatibility feature that
   `vlagent` lacks. It otherwise adds configuration without a VictoriaLogs-specific advantage.

If `vlagent` is selected, verify these boundaries before removing Vector:

- Invert `kubernetesCollector.excludeFilter` to preserve opt-in pod collection.
- Preserve the `app`, namespace, message, timestamp, and stream contracts used by `hops`.
- Configure the audit file with persistent checkpoints, `stageTimestamp`, static identity fields,
  and native VictoriaLogs remote write.
- Establish initial audit-file behavior without importing old files or losing cutover records.
- Compare Vector and `vlagent` briefly with distinguishable collector fields, then remove duplicate
  records before the normal retention window resumes.

An isolated v1.52.0 file-tail check established the checkpoint boundary. With no checkpoint,
`vlagent` reads a pre-existing matched file from byte zero. It stores path, inode, fingerprint, and
offset in `vlagent-file-checkpoints.json`, resumes without duplicates after restart, and follows the
create-and-rename rotation strategy through both the old inode and the replacement file. It does
not support `copytruncate`.[^vlagent-tail]

The audit cutover must therefore avoid matching the existing `kube-apiserver.log`, which would
backfill its contents. The no-loss and no-backfill procedure is to deploy `vlagent` first against a
new, exact audit filename, then change the kube-apiserver audit path so the file is created only
after the collector is watching. Vector continues reading the old exact filename until all control
plane nodes use the new path. Persistent node-local checkpoint storage must survive collector Pod
replacement before Vector is removed.

### Phase 7: remove stale documentation and configuration

1. Remove obsolete Vector VRL, ConfigMaps, ports, environment variables, tests, and chart values.
2. Remove or replace `docs/memory-bank/ceph-etcd-diagnostics-plan.md`, whose completed dashboard
   description no longer matches the current dashboard.
3. Keep the dated Ceph and etcd investigation as historical evidence.
4. Record the final collector decision in an ADR and reference this investigation.
5. Validate all changed manifests with `pre-commit run --files <changed-files>`.

## Lessons learned

Temporary diagnostic sources need an explicit removal condition. A parser's continued activity does
not prove that its output still has a consumer. Source volume, saved queries, alerts, and the
incident state should be reviewed before treating collector-specific behavior as an architecture
requirement.

Noise should be removed as close to its source as the required evidence allows. Downstream filters
save transport and storage, but they do not reduce kube-apiserver audit work, Ceph formatting,
container-runtime writes, or an SELinux audit storm.

## References

- [Ceph logging and debug settings][ceph-logging]
- [Kubernetes auditing][kubernetes-audit]
- [Kubernetes audit policy API][kubernetes-audit-api]
- [VictoriaLogs `vlagent` documentation][vlagent]
- [VictoriaMetrics collector benchmark][collector-benchmark]
- [Vector operator experience][vector-reddit]
- [Collector benchmark discussion][collector-reddit]
- [Vector Kubernetes performance discussion][vector-performance]
- [External DNS v0.21.0 release][external-dns-release]
- [Recyclarr console logging][recyclarr-logging]
- [qBittorrent structured log API][qbittorrent-log-api]
- [`vlagent` overload buffering issue][vlagent-buffering]
- [`vlagent` retry behavior issue][vlagent-retry]
- [`vlagent` file deletion issue][vlagent-file]
- [Ceph and etcd incident investigation][ceph-etcd-investigation]

[ceph-logging]: https://docs.ceph.com/en/latest/rados/troubleshooting/log-and-debug/
[kubernetes-audit]: https://v1-35.docs.kubernetes.io/docs/tasks/debug/debug-cluster/audit/
[kubernetes-audit-api]: https://kubernetes.io/docs/reference/config-api/apiserver-audit.v1/
[vlagent]: https://docs.victoriametrics.com/victorialogs/vlagent/
[collector-benchmark]: https://victoriametrics.com/blog/log-collectors-benchmark-2026/
[vector-reddit]: https://www.reddit.com/r/kubernetes/comments/1kv42qk/
[collector-reddit]: https://www.reddit.com/r/kubernetes/comments/1rywm7f/
[vector-performance]: https://github.com/vectordotdev/vector/discussions/15977
[external-dns-release]: https://github.com/kubernetes-sigs/external-dns/releases/tag/v0.21.0
[recyclarr-logging]: https://recyclarr.dev/cli/common/
[qbittorrent-log-api]: https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)
[vlagent-buffering]: https://github.com/VictoriaMetrics/VictoriaLogs/issues/816
[vlagent-retry]: https://github.com/VictoriaMetrics/VictoriaLogs/issues/1499
[vlagent-file]: https://github.com/VictoriaMetrics/VictoriaLogs/issues/1552

[^rbd-selinux]: [Kubernetes SELinux relabeling KEP][kubernetes-selinux] and
    [ceph-csi OperatorConfig API][ceph-csi-operator-config]
[^talos-selinux-issue]: [Talos issue 13938][talos-selinux-issue]
[^vlagent-tail]: [`vlagent` tailer source][vlagent-tailer] and
    [`vlagent` documentation][vlagent]

[ceph-csi-operator-config]: https://github.com/ceph/ceph-csi-operator/releases/tag/v1.0.4
[kubernetes-selinux]: https://kubernetes.io/docs/tasks/configure-pod-container/security-context/
[talos-selinux-issue]: https://github.com/siderolabs/talos/issues/13938
[vlagent-tailer]: https://github.com/VictoriaMetrics/VictoriaLogs/blob/master/app/vlagent/tail/tailer.go
[ceph-etcd-investigation]: ceph-mon-quorum-loss-etcd-slowness-2026-04-08.md
