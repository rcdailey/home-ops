# Scripts Directory Rules

**IMPORTANT:** Scripts-specific directives that extend root CLAUDE.md

## Python Development

- **Dependencies**: Use virtual environments with requirements.txt
- **App-Scout**: Reference @scripts/app-scout/README.md for deployment discovery patterns

## GitHub CLI Optimization

- **GraphQL Priority**: Batch queries with GraphQL over REST for performance

## Hook Locations

- **Pre-commit scripts**: @scripts/pre-commit/ directory
- **Available validators**:
  - check-dependencies.sh: Ensures required tools are available
  - reloader-validator.py: Validates reloader annotations
  - validate-sops-config.sh: Validates SOPS configuration
  - validate-sops-k8s.sh: Validates SOPS Kubernetes secrets

## Organization

- **Common functions**: lib/common.sh
- **Bootstrap**: bootstrap-apps.sh for cluster initialization
- **Tools**:
  - app-scout/ (K8s deployment pattern discovery)
  - update-gitignore/ (gitignore template maintenance)

## Available Scripts

- **app-scout.sh**: Kubernetes migration discovery tool
- **bootstrap-apps.sh**: Application bootstrap for cluster initialization
