# Schema Management Guide for Claude

This document outlines the proper process for converting Kubernetes CustomResourceDefinitions (CRDs)
to JSON Schema format for YAML Language Server integration.

## Overview

JSON Schema files extracted from Kubernetes CRDs for YAML Language Server validation/autocomplete.
The `annotate-yaml.py` script auto-detects and maps schemas to YAML files.

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

**ALWAYS verify source files are CRDs, not converted schemas:**

CRDs have `apiVersion: apiextensions.k8s.io/v1`, `kind: CustomResourceDefinition`, with schema at
`.spec.versions[0].schema.openAPIV3Schema`

### Conversion Process

**NEVER manually convert. Use automated tooling:**

```bash
#!/usr/bin/env bash
base_url="https://raw.githubusercontent.com/vendor/repo/main/deploy/crd"
output_dir="schemas/vendor-name"
crd_files=("vendor.com_resource_crd.yaml")

mkdir -p "$output_dir"
for crd in "${crd_files[@]}"; do
    filename=$(basename "$crd" .yaml | sed 's/_crd$//')
    output_file="${output_dir}/${filename}.json"

    curl -s "${base_url}/${crd}" | \
        yq eval '.spec.versions[0].schema.openAPIV3Schema' - | \
        yq eval -o=json '.' - | \
        jq '. + {"$schema": "http://json-schema.org/draft-07/schema#"}' > "$output_file"

    jq empty "$output_file" 2>/dev/null && echo "✓ $crd" || (echo "✗ $crd"; rm -f "$output_file")
done
```

**Key Rules:**
1. Extract `.spec.versions[0].schema.openAPIV3Schema`
2. Add `"$schema": "http://json-schema.org/draft-07/schema#"`
3. Filename: `group_resource.json`
4. Validate with `jq empty schema.json`

## Schema Detection Logic

`annotate-yaml.py` uses dynamic detection:

- **Filename:** `group_resource.json` (split on `_`)
- **Kind:** First word of schema description
- **Version:** From group (`fpga.intel.com` → `v2`, others → `v1`)
- **Resource key:** `{api_version}/{kind}` (e.g., `deviceplugin.intel.com/v1/GpuDevicePlugin`)

## Adding New Vendor Schemas

1. **Create directory:** `mkdir -p schemas/vendor-name`
2. **Identify CRDs:** Find upstream repo, raw GitHub URLs, verify CRD structure
3. **Convert:** Modify template script (update base_url, output_dir, crd_files)
4. **Verify:** `python3 scripts/annotate-yaml.py --dry-run`, test with sample YAML
5. **Validate:** Check JSON validity, schema detection, VS Code integration

## Troubleshooting

**Common Issues:**

1. **Invalid schema** → Downloaded full CRD, extract `.spec.versions[0].schema.openAPIV3Schema`
2. **Schema not detected** → Fix filename to `group_resource.json` pattern
3. **No Kind found** → Schema description must start with Kind name
4. **Version mismatch** → Update version logic in `extract_resource_from_schema()`

**Validation Checklist:**

- Source files are CRDs with OpenAPI schemas
- Output includes `"$schema"` field, follows `group_resource.json` naming
- `annotate-yaml.py` detects schemas, test YAML gets annotations

Conversion should be fully automated with no manual schema editing.
