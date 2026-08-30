# OpenTelemetry follow-up findings

- **Date:** 2026-08-30
- **Status:** PARTIALLY RESOLVED

## Summary

The observability review found identity gaps and noisy alerts, but no telemetry loss. The Plex error
bursts came from short AAC decoder storms in one transcode session. OpenCloud also produced
persistent partial traces whose missing parent boundary starts in its `storage-system` service.

## Symptoms

- About 45,250 Kubernetes event records had no `service.name`.
- Plex emitted two bursts of about 43,000 error records each.
- VolSync source pods and cache PVCs triggered alerts during normal backup work.
- Nine of 100 representative traces from a fixed 24-hour window had no root span.
- Collectors warned that the `otlp` exporter type alias was deprecated.

## Investigation

Kubernetes event samples had `event.domain: k8s` and the `k8sobjectsreceiver` scope. They retained
event namespace and object attributes but had no pod or container identity.

Plex diagnostics covered the 2026-08-28 and 2026-08-29 evening bursts. Each burst contained about
42,925 AAC decoder errors over roughly 15 seconds from one transcode session. Plex, pod, network,
and NFS evidence did not show a delivery failure. Shield logs were unavailable for both windows, so
the playback result is unknown. The credits mismatch message was a separate detection problem.

Plex also logged 21 media analysis failures over seven days. The records named files that no longer
existed at their library paths. Available evidence does not distinguish expected import replacement
from stale Plex metadata, so no storage or application change was made for those records.

VolSync source pods consistently used the `volsync-src-<application>-<suffix>` pattern over 72
hours. Their cache claims used `volsync-src-<application>-cache`. Pod phase series appeared first
without `k8s.node.name` while Pending and later with the node after scheduling. The changing label
set created two alert identities for one pod; it was not a second pod or collector.

The trace search returned nine rootless traces among 100 representative traces from a fixed
24-hour window. All rootless examples contained OpenCloud `gateway` or `storage-system` spans.
Three old trace IDs were fetched after ingestion had completed. Each still contained 33 spans, no
root span, and one absent parent at the `storage-system` `appctx` span. This rules out ingestion
delay and places the broken boundary before `storage-system` creates `appctx`.

OpenCloud 7.4.0 source accounts for this boundary. Its Reva HTTP handler extracts an incoming W3C
`traceparent` before starting the `rhttp` `appctx` span. OpenTelemetry represents that upstream
parent as a remote, non-recording span context. OpenCloud exports its local descendants under the
incoming trace ID, but it cannot export the parent span created by the external caller.

Collector 0.158.0 documentation confirms that `otlp_grpc` is the supported exporter type and that
persistent queues remain configured through `sending_queue.storage`. It also confirms the existing
`otelcol_exporter_send_failed_*` and `otelcol_exporter_enqueue_failed_*` counters. Their absence is
normal until the corresponding failure path occurs.

## Root cause

The anonymous logs were source-generated Kubernetes events without a service resource attribute.

The Plex bursts were malformed AAC input handled by the transcoder. Repeated decoder messages made
one short condition appear as tens of thousands of independent failures. The credits mismatch
message means one Plex item has media versions with incompatible durations. Plex stores one marker
per item, so it skips credits detection rather than apply a wrong marker to another version.

Normal VolSync mover startup passes through Pending before scheduling. Because node identity is
added only after scheduling, the same pod temporarily has metric series with different label sets.
The generic rule preserved those labels and created duplicate alert identities.

OpenCloud accepts a sampled remote W3C parent and exports the local child spans. The remote parent
is outside OpenCloud's process and telemetry pipeline, so it is not present in VictoriaTraces. This
is expected propagation behavior, not Collector loss, delayed ingestion, or local sampling.

## Resolution

- Kubernetes events receive `service.name: kubernetes-events` in their source pipeline.
- Credits mismatch records remain available and alert at a bounded rate when more than ten occur in
  one hour.
- Plex transcode storms alert once a five-minute window exceeds 100 records. Missing media analysis
  failures alert once a 15-minute window exceeds five records.
- Generic pod and PVC capacity alerts exclude only VolSync source movers and source cache claims.
- `PodNotReady` aggregates by namespace and pod, so node label transitions cannot duplicate it.
- Kube State Metrics exposes each ReplicationSource's latest result and last sync time. Dedicated
  alerts cover failed movers and backups older than 12 hours, one eight-hour schedule plus four
  hours of grace.
- Collector exporters use `otlp_grpc/gateway` with their existing retry and persistent queue
  settings.
- `hops query traces --trace-id` reports persisted roots, services, and missing parent boundaries.

OpenCloud was not changed. The rootless display distinguishes these externally rooted traces from
complete local requests. Revisit only if a trace with no valid inbound `traceparent` loses its local
root, or if an expected local upstream service fails to export the parent.

## References

- [Observability architecture][observability]
- [OpenTelemetry standardization decision][otel-decision]
- [OpenCloud 7.4.0 release][opencloud-release]
- [OpenTelemetry trace API][otel-trace-api]

[observability]: ../architecture/observability.md
[otel-decision]: ../adr/0001-standardize-observability-on-opentelemetry.md
[opencloud-release]: https://github.com/opencloud-eu/opencloud/releases/tag/v7.4.0
[otel-trace-api]: https://opentelemetry.io/docs/specs/otel/trace/api/
