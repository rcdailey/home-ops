"""Validate domain: VMRule validation and other checks."""

from __future__ import annotations

import platform
import sys
import tarfile
import tempfile
from pathlib import Path

import click

from hops._format import info
from hops._runner import run

# vmalert binary lives in the scripts directory
_SCRIPTS_DIR = Path(__file__).parent.parent
_VMALERT_BINARY = _SCRIPTS_DIR / "vmalert"
_DEFAULT_VMRULES_DIR = "kubernetes/apps/observability/vmrules"


def _detect_platform() -> str:
    """Detect OS and architecture for download."""
    os_name = platform.system().lower()
    if os_name not in ("linux", "darwin"):
        info(f"error: unsupported OS: {os_name}")
        sys.exit(1)
    machine = platform.machine().lower()
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    arch = arch_map.get(machine)
    if not arch:
        info(f"error: unsupported architecture: {machine}")
        sys.exit(1)
    return f"{os_name}-{arch}"


def _get_latest_release() -> str:
    """Get the latest VictoriaMetrics release tag."""
    import json
    import urllib.request

    url = "https://api.github.com/repos/VictoriaMetrics/VictoriaMetrics/releases/latest"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
            return data["tag_name"]
    except Exception as e:
        info(f"error: failed to get latest release: {e}")
        sys.exit(1)


def _download_vmalert() -> None:
    """Download vmalert binary if not present."""
    if _VMALERT_BINARY.exists():
        return

    plat = _detect_platform()
    version = _get_latest_release()
    filename = f"vmutils-{plat}-{version}.tar.gz"
    url = f"https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/{version}/{filename}"

    info(f"Downloading vmutils {version} for {plat}...")

    import urllib.request

    tmp_path = Path(tempfile.gettempdir()) / filename
    try:
        urllib.request.urlretrieve(url, tmp_path)
    except Exception as e:
        info(f"error: download failed: {e}")
        sys.exit(1)

    # Extract vmalert-prod from tarball
    with tarfile.open(tmp_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name == "vmalert-prod":
                f = tar.extractfile(member)
                if f:
                    _VMALERT_BINARY.write_bytes(f.read())
                    _VMALERT_BINARY.chmod(0o755)
                    break
        else:
            info("error: vmalert-prod not found in archive")
            sys.exit(1)

    tmp_path.unlink(missing_ok=True)
    info("vmalert downloaded successfully")


@click.group()
def cli():
    """Validation commands."""


@cli.command()
@click.argument("path", default=_DEFAULT_VMRULES_DIR)
@click.option("--clean", is_flag=True, help="Remove downloaded vmalert binary and exit")
def vmrules(path: str, clean: bool):
    """Validate VMRule YAML files using vmalert -dryRun.

    Automatically downloads vmalert binary if not present.
    """
    if clean:
        if _VMALERT_BINARY.exists():
            _VMALERT_BINARY.unlink()
            info("Cleaned up vmalert binary")
        else:
            info("No vmalert binary to clean")
        return

    _download_vmalert()

    vmrules_dir = Path(path)
    if not vmrules_dir.is_dir():
        info(f"error: directory not found: {path}")
        raise SystemExit(1)

    # Find YAML files (excluding kustomization)
    rule_files = sorted(
        f for f in vmrules_dir.glob("*.yaml") if "kustomization" not in f.name
    )
    rule_files.extend(
        sorted(f for f in vmrules_dir.glob("*.yml") if "kustomization" not in f.name)
    )

    if not rule_files:
        info(f"No VMRule files found in {path}")
        return

    info(f"Validating {len(rule_files)} VMRule files in {path}")

    # Check for yq
    yq_check = run(["yq", "--version"], timeout=5, check=False)
    if yq_check.returncode != 0:
        info("error: yq is required for VMRule extraction")
        raise SystemExit(1)

    failed = False
    for rule_file in rule_files:
        # Extract spec from VMRule CRD
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = run(
                ["yq", "eval", ".spec", str(rule_file)],
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                info(f"  FAIL {rule_file.name}: yq extraction failed")
                failed = True
                continue

            Path(tmp_path).write_text(result.stdout)

            # Validate with vmalert
            val_result = run(
                [str(_VMALERT_BINARY), f"-rule={tmp_path}", "-dryRun"],
                timeout=15,
                check=False,
            )
            if val_result.returncode == 0:
                info(f"  OK   {rule_file.name}")
            else:
                info(f"  FAIL {rule_file.name}")
                # Show validation errors
                for line in (val_result.stderr or val_result.stdout or "").split("\n"):
                    if any(w in line.lower() for w in ("error", "fail", "invalid")):
                        info(f"       {line.strip()}")
                failed = True
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    if failed:
        info("\nVMRule validation failed")
        raise SystemExit(1)
    else:
        info("\nAll VMRules are valid")
