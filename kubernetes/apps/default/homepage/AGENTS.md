# Homepage Configuration

## Icons

Homepage automatically resolves icons from [Dashboard Icons][dashboard-icons]. Use the icon name
directly without URL or extension:

```yaml
- MyApp:
    icon: plex          # Resolved from dashboard-icons
    icon: mdi-flask     # Material Design Icons prefix
    icon: si-github     # Simple Icons prefix
```

### Requirements

- MUST verify icon existence with `./scripts/icon-search.py <name>` before adding to services.yaml
- MUST use Dashboard Icons when available (prioritize over mdi-/si- prefixes)
- MUST use `icons/` subdirectory only for icons not available in Dashboard Icons

### Verification

```bash
./scripts/icon-search.py donetick      # Check if icon exists
./scripts/icon-search.py --url plex    # Get CDN URL for debugging
```

[dashboard-icons]: https://github.com/homarr-labs/dashboard-icons
