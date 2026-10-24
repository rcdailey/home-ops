# Cloudflare AI bot blocking on the cluster zone

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decision:** Block AI bots on all pages of the `${SECRET_DOMAIN}` zone.

## Context and Problem Statement

A security audit found Bot Fight Mode and AI bot blocking turned off on the zone that serves the
cluster's public routes through the Cloudflare Tunnel. Automated AI agents that crawl sites and scan
for vulnerabilities add load and probe these routes.

## Considered Options

- **Block AI bots** - blocks verified and unverified bots that Cloudflare classifies as AI crawlers.
  Free plan.
- **Bot Fight Mode** - challenges known bot patterns. Free plan, but it applies to the whole zone,
  cannot be skipped by WAF rules, and [may challenge API or mobile app traffic][bfm]. That risks the
  Immich, Home Assistant, Plex, and OpenCloud apps and the Flux GitHub webhook.
- **Rate limiting rule** - the Free plan allows one rule, matched on path only, with fixed 10 second
  periods and no counting of failed logins. A limit low enough to slow password guessing would also
  trip on normal app bursts.

## Decision Outcome

Chosen option: **Block AI bots**, because the zone hosts private apps that no AI crawler needs, so
blocking costs nothing. Bot Fight Mode and rate limiting stay off for the reasons above.

Enabling it also changed the zone's `ai_training` setting from `disabled` to `disallow`. Managed
`robots.txt` stays off. Other zones are unchanged; `recyclarr.dev` is a public docs site that AI
search should still reach.

## Verification and Revert

Confirm the setting:

```sh
mise x -- cf bot-management get -z "$SECRET_DOMAIN" | jq -c '{ai_bots_protection, ai_training}'
```

Expected: `{"ai_bots_protection":"block","ai_training":"disallow"}`.

Revert:

```sh
mise x -- cf bot-management update -z "$SECRET_DOMAIN" --ai-bots-protection disabled
```

Re-read the setting afterward, and confirm `ai_training` returned to `disabled`.

## References

- [Block AI bots][block-ai]
- [Bot Fight Mode][bfm]
- [Rate limiting rules availability][rate-limit]

[block-ai]: https://developers.cloudflare.com/bots/additional-configurations/block-ai-bots/
[bfm]: https://developers.cloudflare.com/bots/get-started/bot-fight-mode/
[rate-limit]: https://developers.cloudflare.com/waf/rate-limiting-rules/
