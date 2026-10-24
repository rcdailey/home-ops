# DMARC quarantine policy on Fastmail domains

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decision:** Publish `v=DMARC1; p=quarantine` at `_dmarc` on the two Cloudflare zones that send
  mail through Fastmail: `rdailey.me` and `${SECRET_DOMAIN}`.

## Context and Problem Statement

A security audit found no DMARC record on any zone. Both Fastmail zones publish SPF with `?all`,
which is [Fastmail's recommended value][fastmail-mx] but marks no sender as unauthorized. Without
DMARC, receivers had no instruction to act on mail that fails authentication, so anyone could spoof
these domains.

Fastmail does not create records for domains whose DNS is hosted elsewhere; the zone owner adds
them. Fastmail [accepts `p=none`, `p=quarantine`, or `p=reject`][fastmail-dmarc] for such domains.

## Considered Options

- **`p=none`** - Fastmail's suggested starting value. It only requests reports and does not change
  delivery, so spoofed mail is still delivered.
- **`p=quarantine`** - receivers send mail that fails both SPF and DKIM alignment to spam.
- **`p=reject`** - receivers refuse that mail outright.

## Decision Outcome

Chosen option: **`p=quarantine`**. Fastmail DKIM-signs all outbound mail with the `fm1`-`fm3`
selectors already published in both zones, so legitimate mail passes DMARC through DKIM alignment.
Quarantine stops spoofed mail from reaching inboxes while leaving it recoverable if a legitimate
sender was missed. Raise to `p=reject` once no legitimate mail has landed in spam.

SPF stays at `?all`, as Fastmail documents.

## Verification and Revert

Confirm the published records:

```sh
dig +short TXT _dmarc.rdailey.me @1.1.1.1
dig +short TXT "_dmarc.$SECRET_DOMAIN" @1.1.1.1
```

Expected: `"v=DMARC1; p=quarantine"`. Fastmail's Settings, Domains screen should still show a green
tick for both domains.

Revert by deleting the `_dmarc` TXT record in each zone, or change `p=quarantine` to `p=none`.

## References

- [Fastmail: Setting up your domain, MX only][fastmail-mx]
- [Fastmail: DMARC][fastmail-dmarc]

[fastmail-mx]: https://www.fastmail.help/hc/en-us/articles/1500000280261-Setting-up-your-domain-MX-only
[fastmail-dmarc]: https://www.fastmail.help/hc/en-us/articles/8703749889807-DMARC
