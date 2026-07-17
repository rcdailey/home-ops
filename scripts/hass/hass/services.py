"""List available services."""

from __future__ import annotations

import click

from hass._client import get_client
from hass._errors import die


def _fetch_registry(client) -> dict[str, dict[str, dict]]:
    """Return {domain: {service_name: service_dict}} from the REST API."""
    data = client.request("services")
    registry: dict[str, dict[str, dict]] = {}
    for entry in data:
        domain = entry["domain"]
        registry[domain] = {}
        for svc_name, svc in entry.get("services", {}).items():
            registry[domain][svc_name] = svc
    return registry


@click.command()
@click.argument("target", required=False)
def cli(target: str | None) -> None:
    """List services. No args: domain summary. Domain: list. domain.service: fields."""
    with get_client() as client:
        registry = _fetch_registry(client)

    if not target:
        for domain in sorted(registry, key=lambda d: -len(registry[d])):
            click.echo(f"{domain:30s} {len(registry[domain]):3d}")
        return

    if "." in target:
        domain, service = target.split(".", 1)
        if domain not in registry:
            die(f"Unknown domain: {domain}")
        if service not in registry[domain]:
            die(f"Unknown service: {target}")
        svc = registry[domain][service]
        click.echo(f"{domain}.{service}")
        desc = svc.get("description", "")
        if desc:
            click.echo(f"  {desc}")
        fields = svc.get("fields", {})
        if fields:
            click.echo()
            for fname, field in fields.items():
                req = " (required)" if field.get("required") else ""
                click.echo(f"  {fname}{req}")
                fdesc = field.get("description", "")
                if fdesc:
                    click.echo(f"    {fdesc}")
        return

    # Domain listing
    if target not in registry:
        die(f"Unknown domain: {target}")
    for svc_name in sorted(registry[target]):
        svc = registry[target][svc_name]
        desc = svc.get("description", "")
        if desc:
            click.echo(f"  {target}.{svc_name:30s} {desc}")
        else:
            click.echo(f"  {target}.{svc_name}")
