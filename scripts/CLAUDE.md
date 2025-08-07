# Scripts Directory Rules

**IMPORTANT:** Scripts-specific directives that extend root CLAUDE.md

## Python Development

- **Dependencies**: Use virtual environments with requirements.txt
- **App-Scout**: Reference @scripts/app-scout/README.md for deployment discovery patterns

## GitHub CLI Optimization

- **GraphQL Priority**: Batch queries with GraphQL over REST for performance

## Hook Locations

- **Pre-commit scripts**: @pre-commit/ directory
- **Available validators**: check-dependencies.sh, kustomize-build-check.sh, validate-sops-*.sh

## Organization

- **Common functions**: lib/common.sh
- **Bootstrap**: Cluster initialization scripts
- **Tools**: app-scout (K8s patterns), update-gitignore (template maintenance)
