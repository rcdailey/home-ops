# Homepage Configuration

## Icons

Homepage automatically resolves icons from [Dashboard Icons][dashboard-icons]. Use the icon name
directly without URL or extension:

```yaml
- Dashboard Icon:
    icon: plex
- Material Design Icon:
    icon: mdi-flask
- Simple Icon:
    icon: si-github
```

### Requirements

- MUST verify icon existence with `./scripts/icon-search.py <name>` before adding to services.yaml
- MUST use Dashboard Icons when available (prioritize over mdi-/si- prefixes)
- MUST use `icons/` subdirectory only for icons not available in Dashboard Icons

### Verification

```bash
./scripts/icon-search.py paperless-ngx # Check if icon exists
./scripts/icon-search.py --url plex    # Get CDN URL for debugging
```

[dashboard-icons]: https://github.com/homarr-labs/dashboard-icons
