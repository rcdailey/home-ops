# Observability Infrastructure Cleanup Analysis

## Executive Summary

Based on systematic analysis of the home-ops repository, **no cleanup is required** for existing infrastructure to prepare for Prometheus + Grafana + Loki deployment. The current monitoring configurations are already observability-ready.

## Current Monitoring State

### Ready for Prometheus Integration

- **metrics-server**: ServiceMonitor enabled (`serviceMonitor.enabled: true`)
- **Rook Ceph**: Monitoring enabled with Prometheus rules (`createPrometheusRules: true`)
- **CloudNative PostgreSQL**: Monitoring enabled
- **Cilium**: ServiceMonitors and dashboards enabled
- **Spegel**: Grafana dashboard enabled
- **MariaDB instances**: Metrics enabled for monitoring

### Infrastructure Components

- **Drift Detection**: Prometheus operator ignore rules already configured
- **Resource Monitoring**: CPU/memory requests/limits defined across applications
- **Health Probes**: Liveness/readiness probes implemented where needed

## Cleanup Assessment

### ✅ No Removals Required

- All existing ServiceMonitor configurations are Prometheus-compatible
- Dashboard enablement flags should remain (will integrate with Grafana)
- Health probes and resource limits provide valuable metrics
- Intel GPU monitoring scripts provide useful cluster insights

### ✅ No Updates Required

- Current monitoring configurations will work immediately with Prometheus
- Drift detection component already handles Prometheus operator scenarios
- Resource requests/limits are appropriately configured

### 🤔 FileRun Elasticsearch Decision

**Current State:**

```yaml
# kubernetes/apps/default/filerun/helmrelease.yaml
ELASTICSEARCH_URL: "http://filerun-elasticsearch:9200"
```

**Analysis:**

- Dedicated Elasticsearch instance serves FileRun's search functionality
- This is **separate** from cluster logging requirements
- **Recommendation**: Keep FileRun Elasticsearch as-is (search ≠ logging)

## Preparation Status

### Infrastructure Readiness: ✅ Complete

- No cleanup needed for existing infrastructure
- Current monitoring configs provide immediate value with Prometheus deployment
- Grafana will consume existing dashboard configurations automatically

### Next Phase Ready

The repository is prepared for observability stack deployment with zero infrastructure modifications required.

## Key Strengths Identified

1. **ServiceMonitor Coverage**: Multiple components already expose Prometheus-compatible metrics
2. **Dashboard Integration**: Cilium and Spegel dashboard configs ready for Grafana
3. **Health Monitoring**: Comprehensive probe coverage provides application health visibility
4. **Resource Tracking**: CPU/memory monitoring enabled across all applications
5. **Operational Monitoring**: Custom GPU monitoring and Ceph cluster monitoring in place

---
*Analysis Date: 2025-08-28*
*Repository State: All monitoring infrastructure observability-ready*
