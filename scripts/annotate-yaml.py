#!/usr/bin/env python3

import argparse
import os
import time
import requests
import yaml
import subprocess
import json
from pathlib import Path
from typing import Dict, List

# ANSI color codes
class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'

# Schema source configuration
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "yaml_schemas")
CACHE_MAX_AGE_DAYS = 7

# Source URLs and patterns
FLUXCD_SCHEMAS_BASE = "https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/"
DATREE_BASE_URL = "https://datreeio.github.io/CRDs-catalog/"
K8S_SCHEMAS_BASE = "https://kubernetesjsonschema.dev/v1.31.0/"
SCHEMASTORE_CATALOG = "https://www.schemastore.org/api/json/catalog.json"

def download_cached_file(url: str, filename: str) -> str:
    """Download and cache a file if it doesn't exist or is stale"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, filename)

    do_download = True
    if os.path.isfile(filepath):
        mtime = os.path.getmtime(filepath)
        if (time.time() - mtime) / (60 * 60 * 24) < CACHE_MAX_AGE_DAYS:
            do_download = False

    if do_download:
        print(f"Downloading {url} to {filepath}...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(response.content)

    return filepath

def build_unified_schema_mapping() -> Dict[str, str]:
    """Build unified schema mapping from all sources with priority order"""
    mapping = {}

    # Priority 1: FluxCD Community schemas
    print("Loading FluxCD Community schemas...")
    add_fluxcd_schemas(mapping)

    # Priority 1.5: Specialized CRD schemas (hard-coded for corner cases)
    print("Loading specialized CRD schemas...")
    add_specialized_crd_schemas(mapping)

    # Priority 2: Datree CRD catalog
    print("Loading Datree CRD schemas...")
    add_datree_schemas(mapping)

    # Priority 3: Kubernetes JSON schemas
    print("Loading Kubernetes JSON schemas...")
    add_k8s_schemas(mapping)

    # Priority 4: SchemaStore
    print("Loading SchemaStore schemas...")
    add_schemastore_schemas(mapping)

    print(f"Built unified mapping with {len(mapping)} schema entries")
    return mapping

def add_fluxcd_schemas(mapping: Dict[str, str]):
    """Add FluxCD Community schemas (Priority 1) - dynamically discovered"""
    try:
        # Use gh CLI to list .json files in fluxcd-community/flux2-schemas
        result = subprocess.run([
            'gh', 'repo', 'view', 'fluxcd-community/flux2-schemas', '--json', 'name'
        ], capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            print(f"Warning: Failed to access FluxCD schemas repo: {result.stderr}")
            return

        # List files using gh browse --no-browser to avoid API limits
        files_result = subprocess.run([
            'gh', 'browse', 'fluxcd-community/flux2-schemas', '--no-browser'
        ], capture_output=True, text=True, timeout=30)

        # Fallback: use subprocess to curl the GitHub raw listing
        try:
            curl_result = subprocess.run([
                'curl', '-s', 'https://api.github.com/repos/fluxcd-community/flux2-schemas/contents'
            ], capture_output=True, text=True, timeout=30)

            if curl_result.returncode == 0:
                files_data = json.loads(curl_result.stdout)
                schema_files = [item['name'] for item in files_data
                              if item['name'].endswith('.json') and
                              item['name'] not in ['_definitions.json', 'all.json']]
        except:
            print("Warning: Failed to discover FluxCD schema files")
            return

        # Parse filenames to extract resource mappings
        # Pattern: {resource}-{group}-{version}.json
        for filename in schema_files:
            base_name = filename[:-5]  # Remove .json
            parts = base_name.split('-')

            if len(parts) >= 3:
                resource = parts[0]  # e.g., ocirepository
                group = parts[1]     # e.g., source
                version = parts[2]   # e.g., v1

                # Build apiVersion from group and version
                if group in ['source', 'helm', 'kustomize', 'notification', 'image']:
                    api_version = f"{group}.toolkit.fluxcd.io/{version}"

                    # Convert resource name to proper Kind
                    kind_mapping = {
                        'ocirepository': 'OCIRepository',
                        'gitrepository': 'GitRepository',
                        'helmrepository': 'HelmRepository',
                        'helmrelease': 'HelmRelease',
                        'helmchart': 'HelmChart',
                        'kustomization': 'Kustomization',
                        'receiver': 'Receiver',
                        'alert': 'Alert',
                        'provider': 'Provider',
                        'bucket': 'Bucket',
                        'imagerepository': 'ImageRepository',
                        'imagepolicy': 'ImagePolicy',
                        'imageupdateautomation': 'ImageUpdateAutomation'
                    }

                    kind = kind_mapping.get(resource, resource.capitalize())
                    resource_key = f"{api_version}/{kind}"

                    if resource_key not in mapping:  # First match wins
                        mapping[resource_key] = FLUXCD_SCHEMAS_BASE + filename

        flux_count = len([k for k in mapping.keys() if 'toolkit.fluxcd.io' in k])
        print(f"Added {flux_count} FluxCD schemas")

    except Exception as e:
        print(f"Warning: Failed to discover FluxCD schemas: {e}")

def add_specialized_crd_schemas(mapping: Dict[str, str]):
    """Add specialized CRD schemas (Priority 1.5) - hard-coded for corner cases"""
    try:
        # Hard-coded mappings for specialized CRDs that need direct schema references
        specialized_schemas = {
            # External-DNS schemas - reference JSON schema from vchirikov/dotfiles
            'externaldns.k8s.io/v1alpha1/DNSEndpoint': 'https://raw.githubusercontent.com/vchirikov/dotfiles/master/jsonschemas/dnsendpoints.externaldns.k8s.io.schema.json',

            # Node Feature Discovery schemas - reference JSON schema from vchirikov/dotfiles
            'nfd.k8s-sigs.io/v1alpha1/NodeFeatureRule': 'https://raw.githubusercontent.com/vchirikov/dotfiles/master/jsonschemas/nodefeaturerules.nfd.k8s-sigs.io.schema.json',

        }

        for resource_key, schema_url in specialized_schemas.items():
            if resource_key not in mapping:  # First match wins
                mapping[resource_key] = schema_url

        specialized_count = len([k for k in mapping.keys() if 'vchirikov/dotfiles' in mapping[k]])
        print(f"Added {specialized_count} specialized CRD schemas")

    except Exception as e:
        print(f"Warning: Failed to add specialized CRD schemas: {e}")

def add_datree_schemas(mapping: Dict[str, str]):
    """Add Datree CRD catalog schemas (Priority 2)"""
    try:
        filepath = download_cached_file(DATREE_BASE_URL + "index.yaml", "datree_index.yaml")
        with open(filepath, 'r') as f:
            datree_data = yaml.safe_load(f)

        for _, entries in datree_data.items():
            for entry in entries:
                api_version = entry.get("apiVersion", "")
                kind = entry.get("kind", "")
                filename = entry.get("filename")
                if api_version and kind and filename:
                    resource_key = f"{api_version}/{kind}"
                    if resource_key not in mapping:  # First match wins
                        mapping[resource_key] = DATREE_BASE_URL + filename

        datree_count = len([k for k in mapping.keys() if 'datreeio.github.io' in mapping[k]])
        print(f"Added {datree_count} Datree schemas")

    except Exception as e:
        print(f"Warning: Failed to load Datree schemas: {e}")

def add_k8s_schemas(mapping: Dict[str, str]):
    """Add Kubernetes JSON schemas (Priority 3) - using known core resources"""
    try:
        # Core v1 resources mapping to kubernetesjsonschema.dev patterns
        k8s_core_resources = {
            'v1/Namespace': 'namespace-v1.json',
            'v1/PersistentVolume': 'persistentvolume-v1.json',
            'v1/PersistentVolumeClaim': 'persistentvolumeclaim-v1.json',
            'v1/Secret': 'secret-v1.json',
            'v1/Service': 'service-v1.json',
            'v1/ConfigMap': 'configmap-v1.json',
            'v1/ServiceAccount': 'serviceaccount-v1.json',
            'apps/v1/Deployment': 'deployment-apps-v1.json',
            'apps/v1/StatefulSet': 'statefulset-apps-v1.json',
            'apps/v1/DaemonSet': 'daemonset-apps-v1.json',
            'batch/v1/Job': 'job-batch-v1.json',
            'batch/v1/CronJob': 'cronjob-batch-v1.json',
            'networking.k8s.io/v1/NetworkPolicy': 'networkpolicy-networking-v1.json',
            'rbac.authorization.k8s.io/v1/ClusterRole': 'clusterrole-rbac-v1.json',
            'rbac.authorization.k8s.io/v1/ClusterRoleBinding': 'clusterrolebinding-rbac-v1.json',
            'rbac.authorization.k8s.io/v1/Role': 'role-rbac-v1.json',
            'rbac.authorization.k8s.io/v1/RoleBinding': 'rolebinding-rbac-v1.json'
        }

        # Use known available version from kubernetesjsonschema.dev
        k8s_version = "v1.14.0"  # Known available version

        for resource_key, filename in k8s_core_resources.items():
            if resource_key not in mapping:  # First match wins
                schema_url = f"https://kubernetesjsonschema.dev/{k8s_version}/{filename}"
                mapping[resource_key] = schema_url

        k8s_count = len([k for k in mapping.keys() if 'kubernetesjsonschema.dev' in mapping[k]])
        print(f"Added {k8s_count} Kubernetes schemas")

    except Exception as e:
        print(f"Warning: Failed to add Kubernetes schemas: {e}")

def add_schemastore_schemas(mapping: Dict[str, str]):
    """Add SchemaStore schemas (Priority 4) - dynamically discovered"""
    try:
        # Download and parse SchemaStore catalog
        response = requests.get(SCHEMASTORE_CATALOG, timeout=10)
        if response.status_code == 200:
            catalog = response.json()
            kustomization_url = None

            # Find the kustomization schema URL
            for schema in catalog.get('schemas', []):
                name = schema.get('name', '').lower()
                if 'kustomization' in name:
                    kustomization_url = schema.get('url', '')
                    break

            # If we found the kustomization schema, map all kustomize.config.k8s.io resources to it
            if kustomization_url:
                kustomize_versions = ['v1alpha1', 'v1beta1', 'v1']
                kustomize_kinds = ['Kustomization', 'Component']

                for version in kustomize_versions:
                    for kind in kustomize_kinds:
                        resource_key = f"kustomize.config.k8s.io/{version}/{kind}"
                        if resource_key not in mapping:  # First match wins
                            mapping[resource_key] = kustomization_url

            schemastore_count = len([k for k in mapping.keys() if 'schemastore.org' in mapping.get(k, '')])
            print(f"Added {schemastore_count} SchemaStore schemas")

    except Exception as e:
        print(f"Warning: Failed to discover SchemaStore schemas: {e}")

def find_schema_url(api_version: str, kind: str, schema_mapping: Dict[str, str], verbose: bool = False) -> str | None:
    """Find schema URL using unified mapping"""
    resource_key = f"{api_version}/{kind}"

    if verbose:
        print(f"Finding schema URL for {resource_key}...", end="")

    schema_url = schema_mapping.get(resource_key)

    if verbose:
        if schema_url:
            print(f"found: {schema_url}")
        else:
            print("not found.")

    return schema_url

def annotate_file(file_path: str, schema_mapping: Dict[str, str], dry_run: bool = False, missing_schemas: List[str] = None):
    docs = []
    schema_info = []
    has_changes = False

    with open(file_path, 'r') as f:
        content = f.read()
    if content.startswith("---"):
        content = content[3:]
    if content.endswith("---"):
        content = content[:-3]
    for doc in content.split("\n---\n"):
        doc = doc.strip()
        if not doc:
            continue
        try:
            loaded_docs = list(yaml.safe_load_all(doc))
            data = loaded_docs[0] if loaded_docs else {}
        except (yaml.YAMLError, IndexError):
            data = {}
        api_version = data.get("apiVersion") if "apiVersion" in data else None
        kind = data.get("kind") if "kind" in data else None

        lines = doc.splitlines()

        # Check for existing schema comment
        existing_schema_url = None
        schema_lines = [ln for ln in lines if ln.strip().startswith("# yaml-language-server: $schema")]
        if schema_lines:
            # Extract URL from existing schema line
            schema_line = schema_lines[0].strip()
            if "=" in schema_line:
                existing_schema_url = schema_line.split("=", 1)[1]

        # Remove any existing schema comment
        lines = [ln for ln in lines if not ln.strip().startswith("# yaml-language-server: $schema")]

        if api_version and kind:
            schema_url = find_schema_url(api_version, kind, schema_mapping, verbose=False)
            if schema_url:
                # Only add if schema URL is different from existing
                if existing_schema_url != schema_url:
                    lines.insert(0, f"# yaml-language-server: $schema={schema_url}")
                    schema_info.append((kind, api_version, schema_url))
                    has_changes = True
                else:
                    # Re-add the existing schema line since it's already correct
                    lines.insert(0, f"# yaml-language-server: $schema={schema_url}")
            else:
                # Track missing schemas for report
                resource_key = f"{api_version}/{kind}"
                if missing_schemas is not None and resource_key not in missing_schemas:
                    missing_schemas.append(resource_key)
        docs.append("\n".join(lines))

    if dry_run:
        if schema_info:
            print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
            for kind, api_version, schema_url in schema_info:
                print(f"  - {Colors.YELLOW}{kind}{Colors.RESET}/{Colors.CYAN}{api_version}{Colors.RESET} :: {Colors.MAGENTA}{schema_url}{Colors.RESET}")
    else:
        if has_changes:
            with open(file_path, 'w') as f:
                f.write("---\n")
                f.write("\n---\n".join(docs) + "\n")
        if schema_info:
            print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
            for kind, api_version, schema_url in schema_info:
                print(f"  + {Colors.YELLOW}{kind}{Colors.RESET}/{Colors.CYAN}{api_version}{Colors.RESET} :: {Colors.MAGENTA}{schema_url}{Colors.RESET}")

def find_yaml_files(paths: List[str]) -> List[str]:
    """Find all YAML files from given paths (files or directories)"""
    yaml_files = []

    for path in paths:
        p = Path(path)
        if p.is_file():
            if p.suffix in ['.yaml', '.yml']:
                yaml_files.append(str(p))
        elif p.is_dir():
            # Recursively find all .yaml and .yml files
            for yaml_file in p.rglob("*.yaml"):
                yaml_files.append(str(yaml_file))
            for yml_file in p.rglob("*.yml"):
                yaml_files.append(str(yml_file))
        else:
            print(f"Warning: {path} does not exist")

    return sorted(yaml_files)

def main():
    parser = argparse.ArgumentParser(description="Add YAML Language Server schema annotations to Kubernetes YAML files")
    parser.add_argument("paths", nargs="+", help="YAML files or directories to process (directories are searched recursively)")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Show what would be changed without modifying files")
    args = parser.parse_args()

    yaml_files = find_yaml_files(args.paths)

    if not yaml_files:
        print("No YAML files found in the specified paths")
        return

    schema_mapping = build_unified_schema_mapping()
    missing_schemas = []

    for yf in yaml_files:
        annotate_file(yf, schema_mapping, dry_run=args.dry_run, missing_schemas=missing_schemas)

    # Phase 3: Report missing schemas
    if missing_schemas:
        print(f"\n{Colors.YELLOW}Missing Schemas Report:{Colors.RESET}")
        print(f"The following {len(missing_schemas)} resource types could not be mapped to schemas:")
        for resource_key in sorted(set(missing_schemas)):
            print(f"  - {Colors.CYAN}{resource_key}{Colors.RESET}")
        print(f"\nConsider contributing schema definitions for these resources or")
        print(f"check if newer versions are available in the schema catalogs.")

if __name__ == "__main__":
    main()
