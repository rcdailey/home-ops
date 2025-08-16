#!/usr/bin/env python3

import sys
import yaml
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import argparse


class ReloaderValidator:
    """Validates that Kubernetes apps using secrets/configmaps have reloader annotations."""

    def __init__(self):
        self.errors = []
        # Pattern that indicates secret/configmap usage requiring reloader
        # Matches any ${UPPERCASE_VARIABLE} which indicates Kustomization substitution from secrets
        self.variable_patterns = [
            r'\$\{[A-Z_][A-Z0-9_]*\}',  # ${SECRET_DOMAIN}, ${ADGUARD_HOME_PASSWORD}, etc.
        ]

    def _load_yaml_document(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Load the first relevant document from a YAML file."""
        try:
            with open(file_path, 'r') as f:
                documents = list(yaml.safe_load_all(f))
                # Return first non-empty document
                for doc in documents:
                    if doc is not None:
                        return doc
                return {}
        except yaml.YAMLError as e:
            print(f"Warning: Could not parse {file_path}: {e}")
            return None
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}")
            return None

    def _extract_app_dir_from_ks_path(self, ks_path: Path) -> Path:
        """Extract app directory from ks.yaml file path."""
        # ks.yaml is always in the app directory
        return ks_path.parent

    def _has_variable_substitution(self, file_path: Path) -> bool:
        """Check if file contains variable patterns requiring reloader."""
        try:
            content = file_path.read_text()
            for pattern in self.variable_patterns:
                if re.search(pattern, content):
                    return True
            return False
        except Exception:
            return False

    def _has_secret_references(self, helmrelease: Dict[str, Any]) -> bool:
        """Check if HelmRelease has direct secret references."""
        def search_dict(obj: Any) -> bool:
            if isinstance(obj, dict):
                # Check for valueFrom.secretKeyRef pattern
                if 'valueFrom' in obj and isinstance(obj['valueFrom'], dict):
                    if 'secretKeyRef' in obj['valueFrom']:
                        return True
                # Check for envFrom with secretRef
                if 'envFrom' in obj:
                    env_from = obj['envFrom']
                    if isinstance(env_from, list):
                        for item in env_from:
                            if isinstance(item, dict) and 'secretRef' in item:
                                return True
                # Check for secret volumes
                if 'type' in obj and obj['type'] == 'secret':
                    return True
                # Recursively search nested dictionaries
                for value in obj.values():
                    if search_dict(value):
                        return True
            elif isinstance(obj, list):
                for item in obj:
                    if search_dict(item):
                        return True
            return False

        return search_dict(helmrelease)

    def _has_configmap_with_variables(self, app_dir: Path) -> bool:
        """Check if app has configMapGenerator with files containing variables."""
        kustomization_path = app_dir / "kustomization.yaml"
        if not kustomization_path.exists():
            return False

        kustomization = self._load_yaml_document(kustomization_path)
        if not kustomization:
            return False

        config_map_generators = kustomization.get('configMapGenerator', [])
        for generator in config_map_generators:
            if isinstance(generator, dict) and 'files' in generator:
                files = generator['files']
                if isinstance(files, list):
                    for file_ref in files:
                        # Handle both "file.yaml" and "key=file.yaml" formats
                        if isinstance(file_ref, str):
                            if '=' in file_ref:
                                file_path = file_ref.split('=', 1)[1]
                            else:
                                file_path = file_ref

                            data_file = app_dir / file_path
                            if data_file.exists() and self._has_variable_substitution(data_file):
                                return True

        return False

    def _find_helmrelease(self, app_dir: Path) -> Optional[Dict[str, Any]]:
        """Find and load the HelmRelease in an app directory."""
        helmrelease_path = app_dir / "helmrelease.yaml"
        if helmrelease_path.exists():
            return self._load_yaml_document(helmrelease_path)
        return None

    def _has_reloader_annotation(self, helmrelease: Dict[str, Any]) -> bool:
        """Check if HelmRelease has reloader annotation in controllers."""
        try:
            controllers = helmrelease.get('spec', {}).get('values', {}).get('controllers', {})
            if isinstance(controllers, dict):
                for controller in controllers.values():
                    if isinstance(controller, dict):
                        annotations = controller.get('annotations', {})
                        if isinstance(annotations, dict):
                            reloader_value = annotations.get('reloader.stakater.com/auto')
                            if reloader_value == "true" or reloader_value is True:
                                return True
            return False
        except Exception:
            return False

    def _needs_reloader_annotation(self, app_dir: Path) -> bool:
        """Check if app needs reloader annotation based on usage patterns."""

        # Pattern 1: Variable substitution in any YAML file in app directory
        for yaml_file in app_dir.rglob("*.yaml"):
            if self._has_variable_substitution(yaml_file):
                return True

        # Pattern 2: Direct secret references in HelmRelease
        helmrelease = self._find_helmrelease(app_dir)
        if helmrelease and self._has_secret_references(helmrelease):
            return True

        # Pattern 3: ConfigMap generator with variables
        if self._has_configmap_with_variables(app_dir):
            return True

        return False

    def _is_app_template_helmrelease(self, helmrelease: Dict[str, Any]) -> bool:
        """Check if HelmRelease uses app-template chart."""
        try:
            chart_ref = helmrelease.get('spec', {}).get('chartRef', {})
            return chart_ref.get('name') == 'app-template'
        except Exception:
            return False

    def _validate_app_from_ks(self, ks_path: Path) -> Optional[str]:
        """Validate a single app based on its ks.yaml file."""
        app_dir = self._extract_app_dir_from_ks_path(ks_path)

        # Load HelmRelease
        helmrelease = self._find_helmrelease(app_dir)
        if not helmrelease:
            # No HelmRelease found - skip validation
            return None

        # Only validate app-template HelmReleases
        if not self._is_app_template_helmrelease(helmrelease):
            return None

        # Check if app needs reloader annotation
        needs_reloader = self._needs_reloader_annotation(app_dir)
        has_reloader = self._has_reloader_annotation(helmrelease)

        if needs_reloader and not has_reloader:
            try:
                relative_path = app_dir.relative_to(Path.cwd())
            except ValueError:
                # If relative path fails, use absolute path
                relative_path = app_dir
            return (f"{relative_path}/helmrelease.yaml: HelmRelease uses secrets/configmaps but missing "
                   f"reloader annotation - add 'reloader.stakater.com/auto: \"true\"' to controller annotations")

        return None

    def validate_ks_files(self, ks_files: List[str]) -> bool:
        """Validate apps based on their ks.yaml files."""
        if not ks_files:
            print("No ks.yaml files provided")
            return True

        total_errors = []

        for ks_file in ks_files:
            ks_path = Path(ks_file)
            if not ks_path.exists():
                continue

            error = self._validate_app_from_ks(ks_path)
            if error:
                total_errors.append(error)

        # Print results
        if total_errors:
            print("\nReloader Validation Errors:")
            for error in total_errors:
                print(f"  ❌ {error}")
            print(f"\nFound {len(total_errors)} validation error(s)")
            return False
        else:
            print(f"✅ All {len(ks_files)} app(s) passed reloader validation")
            return True

    def validate_all_apps(self) -> bool:
        """Validate all apps by finding all ks.yaml files."""
        apps_base = Path("kubernetes/apps")
        if not apps_base.exists():
            print("kubernetes/apps directory not found")
            return True

        # Find all ks.yaml files
        ks_files = list(apps_base.rglob("ks.yaml"))
        ks_file_strings = [str(f) for f in ks_files]

        return self.validate_ks_files(ks_file_strings)


def main():
    parser = argparse.ArgumentParser(description="Validate reloader annotations for Kubernetes apps")
    parser.add_argument("files", nargs="*", help="Specific ks.yaml files to validate (default: all apps)")

    args = parser.parse_args()

    validator = ReloaderValidator()

    if args.files:
        success = validator.validate_ks_files(args.files)
    else:
        success = validator.validate_all_apps()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
