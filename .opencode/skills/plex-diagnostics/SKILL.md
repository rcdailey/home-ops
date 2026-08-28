---
name: plex-diagnostics
description: >-
  Use when diagnosing Plex playback stalls, buffering or spinners, NVIDIA Shield playback failures,
  client timeouts, or correlating Plex client, server, storage, and network evidence. Do NOT use for
  Plex deployment or configuration changes without a playback incident.
---

# Plex diagnostics

Correlate the Shield's rolling Plex logs with server logs, cluster metrics, and UniFi path counters.

## Workflow

1. Derive the smallest useful window from the report. Ask when the symptom occurred only when the
   user gave no usable relative or absolute time.
2. Run `./scripts/plex-client-diagnose.py --from <duration>` for a recent incident or `--at
   "<timestamp>"` for a known event. Use `--help` for syntax.
3. Report the narrowest supported failure domain from `Assessment`, then the incident evidence that
   supports it. Distinguish an immediate failure from an unconfirmed physical component.
4. Treat collection notes as limitations. Never silently infer from an unavailable source.
5. Load `unifi-operations` only when the report requires manual network follow-up. Use the known
   Media Flex history at `docs/investigations/media-flex-port-flapping-2026-04-18.md` without
   restating it here.

## Failure behavior

- The Shield endpoint is a rolling buffer. State when the requested incident is outside its range.
- Preserve partial findings when one source fails, and name the missing boundary.
- Do not mutate Plex, Kubernetes, or UniFi state during diagnosis.

## Verification

Require a successful command exit before calling the report complete. Confirm the output window
covers the user's incident and that every root-cause claim cites matching evidence from that window.
