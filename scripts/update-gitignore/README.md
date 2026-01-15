# Gitignore Generator

Builds `.gitignore` from modular components.

## Usage

```bash
./scripts/update-gitignore/update.sh
```

## Customization

- **Custom patterns**: Edit files in `custom/` directory
- **Template types**: Edit `templates.txt` (supports comments with `#`)
- **File order**: Use `01-`, `02-` prefixes in `custom/`

## Current Structure

- `custom/01-secrets.gitignore` - Project secrets and sensitive files
- `custom/02-kubernetes.gitignore` - Cluster and config files
- `custom/03-project.gitignore` - Project-specific artifacts
- `templates.txt` - Gitignore.io template names (one per line)

## Templates Covered

The `templates.txt` already includes templates that cover common patterns:

- `.DS_Store` (macOS template)
- `Thumbs.db` (Windows template)
- `.venv/` (Python template)

Only add custom patterns for project-specific needs.
