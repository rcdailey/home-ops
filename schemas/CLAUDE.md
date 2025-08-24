# Schema Management Guide for Claude

This document outlines the proper process for converting Kubernetes CustomResourceDefinitions (CRDs)
to JSON Schema format for YAML Language Server integration.

## Overview

The `schemas/` directory contains JSON Schema files extracted from Kubernetes CRDs. These schemas
enable VS Code YAML Language Server to provide validation and autocomplete for custom resources. The
`annotate-yaml.py` script automatically detects and maps these schemas to YAML files.

## Directory Structure

```txt
schemas/
├── CLAUDE.md                    # This guide
├── intel-device-plugins/        # Intel Device Plugin schemas
│   ├── deviceplugin.intel.com_gpudeviceplugins.json
│   ├── deviceplugin.intel.com_dlbdeviceplugins.json
│   ├── fpga.intel.com_acceleratorfunctions.json
│   └── ... (other Intel schemas)
└── <vendor>/                    # Future vendor schema directories
```

## Converting CRDs to JSON Schemas

### CRITICAL: Verify Source Files

**ALWAYS verify that source files are actual CRDs, not already converted schemas:**

1. **Check file structure** - CRDs have this structure:

   ```yaml
   apiVersion: apiextensions.k8s.io/v1
   kind: CustomResourceDefinition
   spec:
     group: example.com
     versions:
       - name: v1
         schema:
           openAPIV3Schema:  # ← This contains the actual schema
   ```

2. **Locate the schema** - The JSON Schema is embedded at `.spec.versions[0].schema.openAPIV3Schema`

### Conversion Process

**NEVER manually convert schemas. ALWAYS use automated tooling:**

```bash
#!/usr/bin/env bash
# Template conversion script

base_url="https://raw.githubusercontent.com/vendor/repo/main/deploy/crd"
output_dir="schemas/vendor-name"

# Create output directory
mkdir -p "$output_dir"

# List of CRD files to convert
crd_files=(
    "vendor.com_resourcename_crd.yaml"
    "vendor.com_anothername_crd.yaml"
)

for crd in "${crd_files[@]}"; do
    # Extract group and resource from filename
    # Expected format: group_resource_crd.yaml or group_resources.yaml
    filename=$(basename "$crd" .yaml)
    filename=$(basename "$filename" _crd)

    output_file="${output_dir}/${filename}.json"

    echo "Converting $crd to $output_file..."

    # Extract OpenAPI schema and convert to JSON Schema format
    curl -s "${base_url}/${crd}" | \
        yq eval '.spec.versions[0].schema.openAPIV3Schema' - | \
        yq eval -o=json '.' - | \
        jq '. + {"$schema": "http://json-schema.org/draft-07/schema#"}' > "$output_file"

    # Verify the conversion worked
    if jq empty "$output_file" 2>/dev/null; then
        echo "✓ Successfully converted $crd"
    else
        echo "✗ Failed to convert $crd"
        rm -f "$output_file"
    fi
done
```

### Key Conversion Rules

1. **Extract the OpenAPI schema**: Use `.spec.versions[0].schema.openAPIV3Schema` from the CRD
2. **Add JSON Schema identifier**: Include `"$schema": "http://json-schema.org/draft-07/schema#"`
3. **Preserve filename format**: Use `group_resource.json` naming convention
4. **Validate output**: Ensure resulting file is valid JSON

### Validation Commands

```bash
# Validate JSON syntax
jq empty schema.json

# Test with yq pipeline
yq eval '.spec.versions[0].schema.openAPIV3Schema' crd.yaml | yq eval -o=json '.' -

# Verify schema structure
jq 'has("properties") and has("$schema")' schema.json
```

## Schema Detection Logic

The `annotate-yaml.py` script uses dynamic detection with these patterns:

### Filename Pattern

- Format: `group_resource.json`
- Example: `deviceplugin.intel.com_gpudeviceplugins.json`
- Extraction: Split on `_`, first part is group, second is resource

### Schema Content Extraction

- **Kind**: First word of schema description field
- **Version**: Extracted from group name
  - `fpga.intel.com` → `v2`
  - All others → `v1` (default)
- **API Version**: `{group}/{version}`

### Resource Key Format

- Pattern: `{api_version}/{kind}`
- Examples:
  - `deviceplugin.intel.com/v1/GpuDevicePlugin`
  - `fpga.intel.com/v2/AcceleratorFunction`

## Adding New Vendor Schemas

### Step 1: Create Vendor Directory

```bash
mkdir -p schemas/vendor-name
```

### Step 2: Identify Source CRDs

- Find the upstream repository containing CRD YAML files
- Identify the raw GitHub URLs for the CRD files
- **Verify** files are CRDs with embedded OpenAPI schemas

### Step 3: Create Conversion Script

```bash
# Copy and modify the template conversion script above
# Update base_url, output_dir, and crd_files array
# Run the conversion script
```

### Step 4: Verify Schema Integration

```bash
# Test schema detection
python3 scripts/annotate-yaml.py --dry-run

# Create test YAML file with new resource
cat > /tmp/test-resource.yaml << EOF
---
apiVersion: vendor.com/v1
kind: NewResource
metadata:
  name: test
spec:
  someField: value
EOF

# Test schema mapping
python3 scripts/annotate-yaml.py /tmp/test-resource.yaml
```

### Step 5: Validate Results

- Ensure schema files are valid JSON
- Verify `annotate-yaml.py` detects the new schemas
- Test VS Code YAML Language Server integration
- Clean up test files

## Troubleshooting

### Common Issues

1. **"Invalid schema" errors**
   - **Cause**: Downloaded full CRD instead of extracting OpenAPI schema
   - **Fix**: Use the yq pipeline to extract `.spec.versions[0].schema.openAPIV3Schema`

2. **"Schema not detected" errors**
   - **Cause**: Filename doesn't follow `group_resource.json` pattern
   - **Fix**: Rename file to match expected pattern

3. **"No Kind found" errors**
   - **Cause**: Schema description doesn't start with Kind name
   - **Fix**: Verify schema description field format

4. **"Version mismatch" errors**
   - **Cause**: Script assumes wrong version for new group
   - **Fix**: Update version detection logic in `extract_resource_from_schema()`

### Validation Checklist

- [ ] Source files are CRDs, not plain schemas
- [ ] Conversion extracts OpenAPI schema portion only
- [ ] Output files include `"$schema"` field
- [ ] Filename follows `group_resource.json` format
- [ ] Schema description starts with Kind name
- [ ] `annotate-yaml.py` detects new schemas
- [ ] Test YAML files get correct schema annotations

## Files Modified

When adding new schemas, these files are typically involved:

- `schemas/{vendor}/` - New schema files
- Test YAML files using the new resources
- `scripts/annotate-yaml.py` - May need updates for new groups/versions

The conversion process should be fully automated and require no manual schema editing.
