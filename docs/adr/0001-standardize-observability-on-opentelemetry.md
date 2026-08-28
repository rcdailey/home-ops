# Standardize telemetry collection on OpenTelemetry

OpenTelemetry owns instrumentation, collection, enrichment, and delivery for metrics, logs, and
traces. Node agents collect node-local data, a singleton observer watches cluster state, a Target
Allocator partitions Prometheus targets, and replicated gateways enforce the shared telemetry
contract before exporting to VictoriaMetrics, VictoriaLogs, and VictoriaTraces.

Pod logs are exported only when the pod has `observability.home-ops/logs=true`; the label applies to
every container in that pod. Platform collectors perform only generic parsing and Kubernetes
enrichment. Parsers that understand an application's private files or grammar remain beside that
application and send normalized OTLP to the gateways.

Every signal uses `service.name`, `service.namespace`, `k8s.cluster.name`,
`k8s.namespace.name`, workload identity, `k8s.pod.name`, `k8s.container.name`, and
`k8s.node.name` where those attributes apply.

Gateways use stable identities and per-replica persistent queues so accepted telemetry survives a
Collector restart. The queues buffer bounded backend outages and are not retention storage. Grafana,
VMAlert, and Alertmanager remain the query, presentation, and alerting layer.

The [observability architecture][architecture] documents the current topology and workload signal
coverage.

[architecture]: ../architecture/observability.md
