"""Shared fixtures and helpers for hops test suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


# Repo root: three levels up from scripts/hops/tests/
REPO_ROOT = Path(__file__).parent.parent.parent.parent
HOPS_SCRIPT = REPO_ROOT / "scripts" / "hops.py"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring a live Kubernetes cluster",
    )


def run_hops(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run the hops CLI with the given arguments.

    Returns the CompletedProcess; never raises on non-zero exit unless check=True.
    Working directory is the repo root so relative paths resolve correctly.
    """
    cmd = [sys.executable, str(HOPS_SCRIPT)] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=check,
    )
