"""Integration tests for the unified target resolver.

These tests call resolver functions directly against a live Kubernetes cluster.
All tests are marked @pytest.mark.integration and can be skipped with:
    pytest -m "not integration"
"""

from __future__ import annotations

import pytest

from hops.core.resolve import TargetKind, resolve


@pytest.mark.integration
def test_resolve_deployment():
    target = resolve("plex", namespace="media")
    assert target.kind == TargetKind.WORKLOAD
    assert target.namespace == "media"
    assert target.workload is not None
    assert target.workload.kind == "deployments"


@pytest.mark.integration
def test_resolve_statefulset():
    target = resolve("victoria-logs-single", namespace="observability")
    assert target.kind == TargetKind.WORKLOAD
    assert target.namespace == "observability"
    assert target.workload is not None
    assert target.workload.kind == "statefulsets"


@pytest.mark.integration
def test_resolve_daemonset():
    target = resolve("victoria-logs-single-vector", namespace="observability")
    assert target.kind == TargetKind.WORKLOAD
    assert target.namespace == "observability"
    assert target.workload is not None
    assert target.workload.kind == "daemonsets"


@pytest.mark.integration
def test_resolve_cronjob():
    target = resolve("recyclarr", namespace="media")
    assert target.kind == TargetKind.WORKLOAD
    assert target.namespace == "media"
    assert target.workload is not None
    assert target.workload.kind == "cronjobs"


@pytest.mark.integration
def test_resolve_cnpg_pods():
    # CNPG pods have no parent workload; PodResolver handles them
    target = resolve("blocky-postgres", namespace="dns-private")
    assert target.kind in (TargetKind.WORKLOAD, TargetKind.POD)
    assert target.namespace == "dns-private"
    assert len(target.pods) > 0


@pytest.mark.integration
def test_resolve_with_namespace():
    # Explicit namespace should produce the same result as auto-detected
    target_auto = resolve("plex")
    target_ns = resolve("plex", namespace="media")
    assert target_auto.namespace == target_ns.namespace
    assert target_auto.name == target_ns.name
    assert target_auto.kind == target_ns.kind


@pytest.mark.integration
def test_resolve_nonexistent_exits():
    with pytest.raises(SystemExit):
        resolve("nonexistent-app-xyz")


@pytest.mark.integration
def test_resolve_explain():
    target = resolve("plex", namespace="media", explain=True)
    assert len(target.explain) > 0
    # Explain trace should contain a human-readable resolution step
    combined = " ".join(target.explain)
    assert "plex" in combined or "workload" in combined.lower()


@pytest.mark.integration
def test_resolve_subchart():
    # "vector" resolves via suffix match: "victoria-logs-single-vector" ends with "-vector"
    target = resolve("vector", namespace="observability")
    assert target.kind == TargetKind.WORKLOAD
    assert target.namespace == "observability"


@pytest.mark.integration
def test_resolve_returns_pods_for_workload():
    # Workload resolution should also populate the pods list
    target = resolve("plex", namespace="media")
    assert target.kind == TargetKind.WORKLOAD
    # plex should have at least one pod
    assert len(target.pods) > 0


@pytest.mark.integration
def test_resolve_homepage():
    target = resolve("homepage", namespace="default")
    assert target.kind == TargetKind.WORKLOAD
    assert target.namespace == "default"


@pytest.mark.integration
def test_resolve_blocky():
    target = resolve("blocky", namespace="dns-private")
    assert target.kind == TargetKind.WORKLOAD
    assert target.namespace == "dns-private"
