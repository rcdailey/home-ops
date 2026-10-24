---
name: cloudflare-cli
description: >-
  Use when querying or changing Cloudflare via the `cf` CLI (installed via mise): zones, DNS
  records, zone settings, WAF rulesets, Zero Trust Access, Cloudflare Tunnels, analytics, or any
  other Cloudflare account resource. Triggers on phrases like "check Cloudflare", "list DNS records
  in Cloudflare", "audit Cloudflare", "tunnel config", or any invocation of `cf`. Do NOT use for
  in-cluster external-dns or cloudflared manifests under `kubernetes/apps/network/`.
---

# Cloudflare CLI (cf)

`cf` covers the full public Cloudflare API, but every result is indented JSON with no prose or
table mode. Unfiltered output wastes context; narrow every call.

Run it as `mise x -- cf ...`. It authenticates with `CLOUDFLARE_API_TOKEN` from the mise secrets;
never print it.

## Discover commands

1. `cf cli search "<action and resource type>" | jq -r '.[].command'`. Keep queries anonymous: no
   domains, IDs, or names.
2. Read only the options you need: `cf <command> --help | rg -A2 -- '--<option-prefix>'`. Do not
   walk nested group `--help` output.
3. For request shape, use `cf schema <command without leading cf>`.

## Narrow output

1. Filter server-side first with the command's options (for example `--type`, `--proxied`,
   `--name-endswith`). Use `-z <domain>` to select a zone.
2. Before choosing fields for an unfamiliar resource, inspect one object's shape:
   `| jq '.[0] | keys'`.
3. Project only the fields needed, as rows: `| jq -r '.[] | [.name, .type, .proxied] | @tsv'`.
4. Summarize large sets with `jq` (`group_by`, `length`, `select`) instead of listing them.
5. Cap row output with `| head -50`; widen only when the narrowed result is insufficient.

Lists return one page; check the command's paging options before concluding a set is complete.
Errors go to stderr; keep `2>&1` visible.

## Mutations

Default to read-only. Change resources only on explicit user request, and preview with
`--dry-run` first. In non-interactive runs, a destructive command without `--force` prints
`Aborted.` and exits 0; verify the result instead of trusting the exit status.
