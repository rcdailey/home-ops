# Contributing to home-ops

## Prerequisites

This repository uses pre-commit hooks for validation. Before contributing, ensure you have the required tools installed.

### Required Tools

```bash
# Install via brew (recommended)
brew install kustomize yq jq kubectl sops

# Or via mise globally
mise use -g kustomize yq kubectl sops
```

### Setup

1. **Install pre-commit**:
   ```bash
   # Via pipx (recommended)
   pipx install pre-commit

   # Or via pip
   pip install pre-commit
   ```

2. **Install pre-commit hooks**:
   ```bash
   pre-commit install
   ```

3. **Test setup**:
   ```bash
   pre-commit run --all-files
   ```

## Pre-commit Scripts

Pre-commit validation scripts are located in `scripts/pre-commit/`:
- `check-dependencies.sh` - Validates required tools are available
- `kustomize-build-check.sh` - Validates kustomization builds
- `validate-sops-k8s.sh` - Server-side Kubernetes validation
- `validate-sops-config.sh` - SOPS configuration validation

## Troubleshooting

### "command not found" errors

If you see errors like `kustomize: command not found`, install the missing tools:

```bash
brew install kustomize yq kubectl sops
```

### Pre-commit hook failures

- **SOPS validation failures**: Ensure your secrets follow the two-Kustomization pattern
- **Kustomize build failures**: Run `kustomize build` in the failing directory for details
- **YAML lint failures**: Fix formatting issues in YAML files

## Development Workflow

1. Make your changes
2. Run `pre-commit run --all-files` to validate
3. Fix any issues
4. Commit your changes (pre-commit runs automatically)
