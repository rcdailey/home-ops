#!/usr/bin/env python3

import argparse
import os
import re
import json
import requests
import yaml
import jsonschema
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from urllib.parse import urlparse

# ANSI color codes
class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RED = '\033[91m'
    RESET = '\033[0m'

# Cache directory for downloaded schemas
CACHE_DIR = Path("/tmp/yaml-validator-cache")
CACHE_DIR.mkdir(exist_ok=True)

# In-memory cache for schemas during script execution
_schema_cache: Dict[str, Tuple[Optional[Dict], Optional[str]]] = {}

def get_cache_path(url: str) -> Path:
    """Generate a cache file path for a schema URL"""
    # Create a safe filename from the URL
    safe_name = re.sub(r'[^\w\-_\.]', '_', url)
    if len(safe_name) > 200:  # Limit filename length
        safe_name = safe_name[:200]
    return CACHE_DIR / f"{safe_name}.json"

def download_schema(url: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Download and cache a schema from URL. Returns (schema, error_message)"""
    # Check in-memory cache first
    if url in _schema_cache:
        return _schema_cache[url]

    cache_path = get_cache_path(url)

    # Check file cache
    if cache_path.exists():
        try:
            with open(cache_path, 'r') as f:
                schema = json.load(f)
                # Store in memory cache
                _schema_cache[url] = (schema, None)
                return schema, None
        except (json.JSONDecodeError, IOError):
            # Cache file is corrupted, remove it
            cache_path.unlink()

    # Download schema
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Try to parse as JSON first
        try:
            schema = response.json()
        except json.JSONDecodeError:
            # Might be YAML (e.g., Kubernetes CRDs)
            try:
                schema = yaml.safe_load(response.text)
            except yaml.YAMLError:
                error_msg = f"Failed to parse schema from {url}"
                # Cache the error to avoid repeated failed attempts
                _schema_cache[url] = (None, error_msg)
                return None, error_msg

        # Cache the schema on disk
        with open(cache_path, 'w') as f:
            json.dump(schema, f, indent=2)

        # Store in memory cache
        _schema_cache[url] = (schema, None)
        return schema, None

    except requests.RequestException as e:
        error_msg = f"Failed to download schema from {url}: {e}"
        # Cache the error to avoid repeated failed attempts
        _schema_cache[url] = (None, error_msg)
        return None, error_msg

def extract_schema_url(content: str) -> Optional[str]:
    """Extract schema URL from YAML content"""
    # Look for yaml-language-server schema annotation
    pattern = r'#\s*yaml-language-server:\s*\$schema=(.+?)(?:\s|$)'
    match = re.search(pattern, content)
    if match:
        return match.group(1).strip()
    return None

def extract_schema_url_for_document(full_content: str, doc_index: int) -> Optional[str]:
    """Extract schema URL for a specific document in multi-document YAML"""
    import re

    # Split content by document separators
    docs = re.split(r'\n---\n', full_content)

    if doc_index >= len(docs):
        return None

    # Look for schema annotation in the current document
    doc_content = docs[doc_index]
    pattern = r'#\s*yaml-language-server:\s*\$schema=(.+?)(?:\s|$)'
    match = re.search(pattern, doc_content)
    if match:
        return match.group(1).strip()

    return None

def is_sops_related_error(error: 'jsonschema.ValidationError', doc: Dict) -> bool:
    """Check if a validation error is related to SOPS variable substitution"""
    import re

    # Get the value that caused the error
    try:
        # Navigate to the error location in the document
        current = doc
        for path_part in error.absolute_path:
            current = current[path_part]

        # Check if the failing value contains SOPS variable syntax
        if isinstance(current, str) and re.search(r'\$\{[^}]+\}', current):
            return True

        # Also check if the error message mentions SOPS patterns
        if re.search(r'\$\{[^}]+\}', str(error.instance)):
            return True

    except (KeyError, TypeError, IndexError):
        # If we can't navigate to the error location, check the error instance
        if hasattr(error, 'instance') and isinstance(error.instance, str):
            if re.search(r'\$\{[^}]+\}', error.instance):
                return True

    return False

def validate_document(doc: Dict, schema: Dict) -> Tuple[bool, List[str]]:
    """Validate a YAML document against a schema"""
    errors = []

    try:
        # Handle Kubernetes CRDs - extract the schema from openAPIV3Schema
        if 'spec' in schema and 'versions' in schema['spec']:
            # This is a Kubernetes CRD, extract the OpenAPI schema
            for version in schema['spec']['versions']:
                if 'schema' in version and 'openAPIV3Schema' in version['schema']:
                    schema = version['schema']['openAPIV3Schema']
                    break

        # Use ErrorTree to collect all validation errors
        # Suppress the deprecation warning about automatic remote reference retrieval
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning,
                                  message=".*Automatically retrieving remote references.*")
            validator = jsonschema.Draft7Validator(schema)
            validation_errors = list(validator.iter_errors(doc))

        if not validation_errors:
            return True, []

        # Filter out SOPS-related errors
        filtered_errors = []
        for error in validation_errors:
            if not is_sops_related_error(error, doc):
                # Format validation error with path context
                path_str = '.'.join(str(p) for p in error.absolute_path) if error.absolute_path else 'root'
                error_msg = f"{path_str}: {error.message}"
                filtered_errors.append(error_msg)

        # If all errors were SOPS-related, consider it passed
        if not filtered_errors:
            return True, []

        return False, filtered_errors

    except jsonschema.SchemaError as e:
        errors.append(f"Schema error: {e.message}")
        return False, errors

    except Exception as e:
        errors.append(f"Validation error: {str(e)}")
        return False, errors

def validate_yaml_file(file_path: str, verbose: bool = False) -> Tuple[int, int, int]:
    """
    Validate a YAML file against its schema.
    Returns tuple of (passed_count, failed_count, skipped_count)
    """
    try:
        with open(file_path, 'r') as f:
            content = f.read()
    except IOError as e:
        print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
        print(f"  {Colors.RED}✗ Failed to read file: {e}{Colors.RESET}")
        return 0, 1, 0

    # Parse YAML documents first
    try:
        # Handle multi-document YAML files
        documents = list(yaml.safe_load_all(content))
        # Filter out None/empty documents
        documents = [doc for doc in documents if doc is not None]

        if not documents:
            if verbose:
                print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
                print(f"  {Colors.YELLOW}⚠ Skipped (no YAML documents found){Colors.RESET}")
            return 0, 0, 1

    except yaml.YAMLError as e:
        print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
        print(f"  {Colors.RED}✗ YAML parsing error: {e}{Colors.RESET}")
        return 0, 1, 0

    # Validate each document with its own schema
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    file_printed = False

    for i, doc in enumerate(documents):
        if not isinstance(doc, dict):
            continue

        # Get document info for display
        api_version = doc.get('apiVersion', 'unknown')
        kind = doc.get('kind', 'unknown')

        # Extract schema URL for this specific document
        schema_url = extract_schema_url_for_document(content, i)

        if not schema_url:
            if verbose:
                if not file_printed:
                    print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
                    file_printed = True
                print(f"  {Colors.YELLOW}⚠ {kind}/{api_version} :: Skipped (no schema annotation){Colors.RESET}")
            total_skipped += 1
            continue

        # Download schema for this document
        schema, schema_error = download_schema(schema_url)
        if not schema:
            if not file_printed:
                print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
                file_printed = True
            print(f"  {Colors.RED}✗ {kind}/{api_version} :: {schema_error}{Colors.RESET}")
            total_failed += 1
            continue

        # Validate document
        is_valid, errors = validate_document(doc, schema)

        if is_valid:
            if verbose:
                if not file_printed:
                    print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
                    file_printed = True
                print(f"  {Colors.GREEN}✓ {kind}/{api_version} :: Valid{Colors.RESET}")
            total_passed += 1
        else:
            if not file_printed:
                print(f"{Colors.BLUE}{file_path}:{Colors.RESET}")
                file_printed = True

            error_count = len(errors)
            error_text = "error" if error_count == 1 else "errors"
            print(f"  {Colors.RED}✗ {kind}/{api_version} :: {error_count} validation {error_text}{Colors.RESET}")

            # Show first few errors to avoid overwhelming output
            for error in errors[:3]:  # Limit to first 3 errors
                print(f"    - {Colors.CYAN}{error}{Colors.RESET}")

            if len(errors) > 3:
                remaining = len(errors) - 3
                print(f"    {Colors.YELLOW}... and {remaining} more errors{Colors.RESET}")

            total_failed += 1

    return total_passed, total_failed, total_skipped

def main():
    parser = argparse.ArgumentParser(
        description='Validate YAML files against their attached schemas'
    )
    parser.add_argument(
        'paths',
        nargs='+',
        help='YAML files or directories to validate'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show all validation results including successful ones'
    )

    args = parser.parse_args()

    # Collect YAML files
    yaml_files = []
    for path_str in args.paths:
        path = Path(path_str)
        if path.is_file() and path.suffix.lower() in ['.yaml', '.yml']:
            yaml_files.append(str(path))
        elif path.is_dir():
            yaml_files.extend([
                str(f) for f in path.rglob('*.yaml')
                if f.is_file()
            ])
            yaml_files.extend([
                str(f) for f in path.rglob('*.yml')
                if f.is_file()
            ])

    if not yaml_files:
        print("No YAML files found in the specified paths")
        return 1

    # Validate files
    total_passed = 0
    total_failed = 0
    total_skipped = 0

    for yaml_file in sorted(yaml_files):
        passed, failed, skipped = validate_yaml_file(yaml_file, verbose=args.verbose)
        total_passed += passed
        total_failed += failed
        total_skipped += skipped

    # Print summary
    total_files = len(yaml_files)
    print(f"\nSummary: {total_files} files processed, "
          f"{Colors.GREEN}{total_passed} passed{Colors.RESET}, "
          f"{Colors.RED}{total_failed} failed{Colors.RESET}, "
          f"{Colors.YELLOW}{total_skipped} skipped{Colors.RESET}")

    # Exit with error code if any validations failed
    return 1 if total_failed > 0 else 0

if __name__ == "__main__":
    exit(main())
