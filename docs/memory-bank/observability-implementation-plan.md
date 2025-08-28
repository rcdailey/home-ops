# Observability Implementation Plan: Prometheus + Grafana + Loki

## Executive Summary

Comprehensive deployment plan for implementing a unified observability stack using
**kube-prometheus-stack** (Prometheus + AlertManager), **Grafana**, and **Loki** in the home-ops
cluster. This plan leverages research from high-quality GitOps repositories and official
documentation to ensure production-ready implementation.

## Research Foundation

### App-Scout Analysis Results

**Component Deployment Patterns:**

- **kube-prometheus-stack**: 192 implementations found, predominantly using dedicated Helm charts
- **Grafana**: 193 implementations found, 99% using official Grafana Helm chart (not app-template)
- **Loki**: 134 implementations found, 100% using official Loki Helm chart (not app-template)

**Key Finding**: All three components should use **dedicated Helm charts** rather than app-template,
following established GitOps community practices.

### Implementation Architecture

Based on analysis of bjw-s-labs/home-ops (732 stars) and onedr0p/home-ops (2509 stars) repositories:

```
observability/
├── kube-prometheus-stack/
├── grafana/
└── loki/
```

## Component Implementation Details

### 1. kube-prometheus-stack (Prometheus + AlertManager)

**Chart Configuration:**

```yaml
Chart: kube-prometheus-stack
Version: 76.5.1+
Repository: prometheus-community
OCI: oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack
```

**Key Configuration Points:**

- **Integrated Components**: Prometheus, AlertManager, node-exporter, kube-state-metrics
- **Grafana Integration**: Disable built-in Grafana (`grafana.enabled: false`) for separate
  deployment
- **Storage**: 55Gi ceph-block PVC for Prometheus data
- **Retention**: 14d retention period, 50GB size-based retention
- **Resource Limits**: 100m CPU request, 2000M memory limit
- **Security Context**: Non-root user (64535:64535)

**Critical Dependencies:**

- Depends on: `rook-ceph-cluster` for storage
- CRD Management: `install.crds: CreateReplace`, `upgrade.crds: CreateReplace`

### 2. Grafana (Visualization)

**Chart Configuration:**

```yaml
Chart: grafana
Version: 9.3.4+
Repository: grafana
OCI: oci://ghcr.io/grafana/helm-charts/grafana
```

**Key Configuration Points:**

- **Datasources**: Pre-configured for Prometheus, Loki, AlertManager
- **Dashboards**: Automated discovery via `grafana_dashboard` label
- **Storage**: Stateless (no persistence required)
- **Authentication**: Admin secret management via External Secrets
- **Resource Limits**: 50m CPU, 512Mi memory
- **Image Renderer**: Enabled for PDF/PNG exports

**Dashboard Categories:**

- Default: cert-manager, external-dns, node-exporter, smartctl, spegel, volsync, zfs
- Ceph: cluster, OSD, pools dashboards
- Flux: cluster, control-plane, logs dashboards
- Kubernetes: API server, global, nodes, namespaces, pods, volumes

### 3. Loki (Log Aggregation)

**Chart Configuration:**

```yaml
Chart: loki
Version: 6.37.0+
Repository: grafana
OCI: oci://ghcr.io/grafana/helm-charts/loki
```

**Key Configuration Points:**

- **Deployment Mode**: SingleBinary (optimal for homelab scale)
- **Storage**: 50Gi ceph-block PVC, filesystem backend
- **Retention**: 14d retention via compactor
- **Schema**: v13 with TSDB index, snappy compression
- **Security**: `auth_enabled: false` (internal cluster use)
- **Dependencies**: Requires `rook-ceph-cluster`

## Storage Strategy

### Storage Requirements Summary

| Component    | Storage Type | Size      | Retention | Storage Class |
| ------------ | ------------ | --------- | --------- | ------------- |
| Prometheus   | Block        | 55Gi      | 14d/50GB  | ceph-block    |
| AlertManager | Block        | 1Gi       | N/A       | ceph-block    |
| Loki         | Block        | 50Gi      | 14d       | ceph-block    |
| Grafana      | None         | Stateless | N/A       | N/A           |

### Storage Class Alignment

- **ceph-block (RWO)**: Perfect for database-like workloads (Prometheus, Loki)
- **No RWX needed**: All components run single-replica for homelab scale
- **Total Storage**: ~106Gi allocated across observability stack

## Network Configuration

### Service Communication

```yaml
# Internal service endpoints (cluster DNS)
prometheus: prometheus-operated.observability.svc.cluster.local:9090
loki: loki-headless.observability.svc.cluster.local:3100
alertmanager: alertmanager-operated.observability.svc.cluster.local:9093
grafana: grafana.observability.svc.cluster.local:3000
```

### HTTPRoute Configuration

```yaml
# External access via existing gateway infrastructure
grafana: grafana.${SECRET_DOMAIN}
prometheus: prometheus.${SECRET_DOMAIN}
alertmanager: alertmanager.${SECRET_DOMAIN}
```

**Gateway Integration:**

- Use existing `internal` gateway in `network` namespace
- HTTPS termination via `sectionName: https`
- Follow established HTTPRoute patterns

## Implementation Sequence

### Phase 1: Core Infrastructure (kube-prometheus-stack)

1. **Create observability namespace** with proper labels/annotations
2. **Deploy kube-prometheus-stack** with Grafana disabled
3. **Configure ServiceMonitor selectors** to discover existing monitors
4. **Validate metrics collection** from existing infrastructure
5. **Set up AlertManager** basic configuration

### Phase 2: Visualization (Grafana)

1. **Deploy Grafana** with pre-configured datasources
2. **Configure dashboard providers** for automated discovery
3. **Import essential dashboards** (Kubernetes, Ceph, Flux)
4. **Create admin credentials** in `secret.sops.yaml` (ONLY sensitive data)
5. **Configure HTTPRoute** for external access

### Phase 3: Log Aggregation (Loki)

1. **Deploy Loki SingleBinary** with filesystem storage
2. **Configure retention policies** via compactor
3. **Set up Grafana-Loki integration**
4. **Configure log shipping** (Promtail or equivalent)
5. **Validate log ingestion and queries**

### Phase 4: Integration & Monitoring

1. **Configure cross-component alerting rules**
2. **Set up dashboard correlations** (metrics + logs)
3. **Implement backup strategies** for configuration/data
4. **Performance tuning** based on actual usage
5. **Documentation and runbooks**

## Directory Structure

Following your established GitOps patterns:

```txt
kubernetes/apps/observability/
├── kustomization.yaml                    # Namespace kustomization (sets namespace + targetNamespace patch)
├── kube-prometheus-stack/
│   ├── ks.yaml                          # Kustomization resource (NO namespace fields)
│   ├── kustomization.yaml               # App-level kustomization
│   ├── helmrelease.yaml                 # Main chart deployment
│   ├── secret.sops.yaml                 # ONLY secrets (admin passwords, tokens)
│   ├── prometheusrules/                 # Custom alerting rules (if needed)
│   └── scrapeconfigs/                   # Additional scrape targets (if needed)
├── grafana/
│   ├── ks.yaml                          # Kustomization resource (NO namespace fields)
│   ├── kustomization.yaml
│   ├── helmrelease.yaml
│   ├── secret.sops.yaml                 # ONLY admin credentials
│   └── dashboard/                       # Custom dashboards (if needed)
└── loki/
    ├── ks.yaml                          # Kustomization resource (NO namespace fields)
    ├── kustomization.yaml
    ├── helmrelease.yaml
    └── prometheus-rule.yaml             # Loki monitoring rules (if needed)
```

## Integration with Existing Infrastructure

### Immediate ServiceMonitor Discovery

Existing monitoring configurations will be automatically discovered:

- **metrics-server**: ServiceMonitor enabled
- **Rook Ceph**: Prometheus rules + monitoring enabled
- **Cilium**: ServiceMonitors + dashboards enabled
- **Spegel**: Grafana dashboard enabled
- **CloudNative PostgreSQL**: Monitoring enabled

### Namespace Configuration

**Parent Namespace Kustomization** (`kubernetes/apps/observability/kustomization.yaml`):

```yaml
---
# yaml-language-server: $schema=https://www.schemastore.org/kustomization.json
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: observability                    # Sets metadata.namespace for child Kustomizations
components:
- ../../components/common
- ../../components/drift-detection
resources:
- ./kube-prometheus-stack/ks.yaml
- ./grafana/ks.yaml
- ./loki/ks.yaml
patches:
- target:
    kind: Kustomization
    group: kustomize.toolkit.fluxcd.io
  patch: |
    - op: add
      path: /spec/targetNamespace
      value: observability                  # Sets spec.targetNamespace for all child apps
```

**Child ks.yaml files** (NO namespace or targetNamespace fields - inherited from parent):

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app grafana                       # NO namespace field here
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  interval: 1h
  path: ./kubernetes/apps/observability/grafana
  postBuild:
    substituteFrom:
    - name: cluster-secrets
      kind: Secret
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  wait: true
  # NO spec.targetNamespace field here - inherited from parent patch
```

**Critical Namespace Rules:**

- Parent kustomization: `namespace: observability` + targetNamespace patch
- Child ks.yaml files: NO `metadata.namespace` or `spec.targetNamespace` fields
- Result: Apps deployed to `observability` namespace automatically

## Resource Planning

### CPU/Memory Allocation

| Component    | CPU Request | CPU Limit | Memory Request | Memory Limit |
| ------------ | ----------- | --------- | -------------- | ------------ |
| Prometheus   | 100m        | -         | -              | 2000Mi       |
| AlertManager | -           | -         | -              | -            |
| Grafana      | 50m         | -         | 128Mi          | 512Mi        |
| Loki         | -           | -         | -              | -            |
| **Total**    | **150m**    | -         | **128Mi**      | **2512Mi**   |

### Node Distribution

- **Control Plane Nodes**: AlertManager, Grafana (lightweight)
- **Worker Nodes**: Prometheus, Loki (storage-heavy)
- **Anti-affinity**: Prevent single points of failure

## Security Considerations

### Authentication & Authorization

- **Grafana**: Admin credentials in `secret.sops.yaml` (ONLY sensitive data)
- **Prometheus/Loki**: Internal cluster access only (no secrets needed)
- **AlertManager**: Webhook tokens in `secret.sops.yaml` (if external alerting configured)

### Network Security

- **Internal Communication**: Cluster DNS service discovery
- **External Access**: HTTPRoute with TLS termination
- **Firewall Rules**: No additional rules needed (internal traffic)

### Data Retention & Privacy

- **Log Retention**: 14d automatic cleanup via compactor
- **Metric Retention**: 14d with 50GB size limit
- **Data Location**: Ceph storage within cluster boundary

## Monitoring the Monitoring

### Health Checks

- **Prometheus**: ServiceMonitor for self-monitoring
- **Grafana**: Built-in health endpoints
- **Loki**: Prometheus rules for Loki monitoring
- **AlertManager**: Dead man switch alerting

### Key Metrics to Monitor

```yaml
# Prometheus health
prometheus_build_info
prometheus_config_last_reload_successful
prometheus_tsdb_head_series

# Loki health
loki_build_info
loki_ingester_memory_series
loki_panic_total

# Grafana health
grafana_build_info
grafana_stat_totals_dashboard
grafana_alerting_rule_evaluation_failures_total
```

## Backup Strategy

### Configuration Backup

- **Grafana Dashboards**: Exported via sidecar to ConfigMaps (non-sensitive)
- **Prometheus Rules**: Version controlled in Git (non-sensitive)
- **AlertManager Config**: Non-sensitive config in HelmRelease values
- **Secrets**: Admin passwords and tokens in `secret.sops.yaml` only

### Data Backup Considerations

- **Prometheus**: Time-series data (14d retention = acceptable loss)
- **Loki**: Log data (14d retention = acceptable loss)
- **Grafana**: Stateless (no persistent data)

**Decision**: Configuration backup only, data retention policy handles data lifecycle.

## Troubleshooting Runbook

### Common Issues & Solutions

**Prometheus Not Scraping Targets:**

```bash
# Check ServiceMonitor discovery
kubectl get servicemonitor -A
kubectl describe prometheus kube-prometheus-stack-prometheus -n observability
```

**Grafana Dashboards Not Loading:**

```bash
# Check sidecar logs
kubectl logs -n observability deployment/grafana -c grafana-sc-dashboards
# Verify dashboard ConfigMaps
kubectl get configmap -n observability -l grafana_dashboard=1
```

**Loki Not Receiving Logs:**

```bash
# Check Loki status
kubectl logs -n observability statefulset/loki
# Test log ingestion
curl -H "Content-Type: application/json" -X POST loki.observability:3100/loki/api/v1/push
```

## Success Metrics

### Implementation Success Criteria

- [ ] All existing ServiceMonitors discovered and scraping
- [ ] Grafana dashboards displaying cluster metrics
- [ ] Loki ingesting and storing logs with 14d retention
- [ ] AlertManager routing basic cluster alerts
- [ ] All components accessible via HTTPRoutes
- [ ] Resource usage within planned limits
- [ ] GitOps workflow functioning (config changes via Git)

### Operational Metrics

- **Prometheus scrape duration**: < 30s average
- **Grafana dashboard load time**: < 3s average
- **Loki query response time**: < 5s for common queries
- **Storage utilization**: < 80% of allocated space
- **Memory usage**: Within defined limits
- **CPU usage**: < 50% of requests under normal load

---

*Implementation Plan Version: 1.0* *Research Date: 2025-08-28* *Based on: bjw-s-labs/home-ops,
onedr0p/home-ops, official documentation*
