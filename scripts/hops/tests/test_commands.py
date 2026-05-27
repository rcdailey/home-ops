"""Integration tests for hops CLI commands.

These tests invoke the hops CLI via subprocess against a live Kubernetes cluster.
All tests are marked @pytest.mark.integration and can be skipped with:
    pytest -m "not integration"
"""

from __future__ import annotations


import pytest

from tests.conftest import run_hops


@pytest.mark.integration
def test_app_list():
    result = run_hops("app", "list")
    assert result.returncode == 0
    assert "NAMESPACE" in result.stdout
    assert "NAME" in result.stdout


@pytest.mark.integration
def test_app_list_namespace():
    result = run_hops("app", "list", "media")
    assert result.returncode == 0
    # Every data row should have "media" in it
    lines = [ln for ln in result.stdout.splitlines() if ln and "NAMESPACE" not in ln]
    assert len(lines) > 0, "expected at least one app in media namespace"
    for line in lines:
        assert "media" in line, f"unexpected namespace in line: {line!r}"


@pytest.mark.integration
def test_app_pod():
    result = run_hops("app", "pod", "plex", "-n", "media")
    assert result.returncode == 0
    assert "POD" in result.stdout


@pytest.mark.integration
def test_app_unhealthy():
    result = run_hops("app", "unhealthy")
    assert result.returncode == 0
    # Either lists unhealthy pods or prints a healthy message
    output = result.stdout
    assert output.strip() != "", "expected some output from app unhealthy"


@pytest.mark.integration
def test_app_diagnose():
    result = run_hops("app", "diagnose", "plex", "-n", "media")
    assert result.returncode == 0
    assert "FLUX" in result.stdout
    assert "SERVICES" in result.stdout
    assert "PODS" in result.stdout


@pytest.mark.integration
def test_app_diagnose_explain():
    result = run_hops("app", "diagnose", "plex", "--explain")
    assert result.returncode == 0
    # With --explain the RESOLVER section is printed
    assert "RESOLVER" in result.stdout


@pytest.mark.integration
def test_app_types():
    result = run_hops("app", "types")
    assert result.returncode == 0
    assert "WORKLOADS" in result.stdout


@pytest.mark.integration
def test_app_events():
    result = run_hops("app", "events")
    assert result.returncode == 0


@pytest.mark.integration
def test_app_secrets():
    result = run_hops("app", "secrets")
    assert result.returncode == 0
    assert "NAMESPACE" in result.stdout


@pytest.mark.integration
def test_flux_status():
    result = run_hops("flux", "status")
    assert result.returncode == 0


@pytest.mark.integration
def test_flux_hr():
    result = run_hops("flux", "hr", "plex", "-n", "media")
    assert result.returncode == 0
    assert "Name" in result.stdout or "plex" in result.stdout


@pytest.mark.integration
def test_flux_hr_list():
    result = run_hops("flux", "hr")
    assert result.returncode == 0
    assert "NAMESPACE" in result.stdout
    assert "NAME" in result.stdout


@pytest.mark.integration
def test_flux_hr_search():
    result = run_hops("flux", "hr", "victoria")
    assert result.returncode == 0
    assert "victoria" in result.stdout


@pytest.mark.integration
def test_flux_ks_list():
    result = run_hops("flux", "ks")
    assert result.returncode == 0
    assert "NAMESPACE" in result.stdout
    assert "NAME" in result.stdout


@pytest.mark.integration
def test_flux_ks_search():
    result = run_hops("flux", "ks", "external")
    assert result.returncode == 0
    assert "external" in result.stdout


@pytest.mark.integration
def test_flux_ks_detail():
    result = run_hops("flux", "ks", "external-secrets")
    assert result.returncode == 0
    assert "Path:" in result.stdout


@pytest.mark.integration
def test_node_list():
    result = run_hops("node", "list")
    assert result.returncode == 0
    assert "NODE" in result.stdout


@pytest.mark.integration
def test_db_status():
    result = run_hops("db", "status")
    assert result.returncode == 0
    assert "blocky-postgres" in result.stdout


@pytest.mark.integration
def test_backup_status():
    result = run_hops("backup", "status")
    assert result.returncode == 0


@pytest.mark.integration
def test_storage_ceph_status():
    result = run_hops("storage", "ceph", "status")
    assert result.returncode == 0
    assert "HEALTH" in result.stdout


@pytest.mark.integration
def test_storage_pvcs():
    result = run_hops("storage", "pvcs")
    assert result.returncode == 0
    assert "NAMESPACE" in result.stdout


@pytest.mark.integration
def test_bad_app_exits_nonzero():
    result = run_hops("app", "pods", "nonexistent-app-xyz")
    assert result.returncode != 0


@pytest.mark.integration
def test_node_disks():
    result = run_hops("node", "disks")
    assert result.returncode == 0
    assert "NODE" in result.stdout
