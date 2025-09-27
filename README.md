# Home Operations

Kubernetes cluster for homelab infrastructure and applications.

## Secret Management

### SOPS vs Infisical

- **SOPS**: Used for bootstrapping Infisical and cluster infrastructure secrets
- **Infisical**: Primary secret management for all application secrets cluster-wide

### Infisical CLI Setup

```bash
# Install CLI
brew install infisical

# Initialize (replace ${SECRET_DOMAIN} with actual domain)
infisical init
# Use URL: https://secrets.${SECRET_DOMAIN}
```

Follow the wizard to configure project and environment settings.
