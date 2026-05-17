# Kometa Quickstart not adopted

- **Status:** Accepted
- **Date:** 2026-05-17
- **Decision:** Keep separate Kometa and ImageMaid CronJobs; do not adopt Kometa Quickstart

## Context and Problem Statement

Kometa (metadata/collections manager) and ImageMaid (Plex image cleanup) run as separate CronJobs on
independent schedules. The Kometa team released [Quickstart][quickstart], a Flask web UI that wraps
both tools and adds a config wizard, overlay previews, and maintenance-window awareness. The
question is whether Quickstart could replace both CronJobs with a single long-running service.

## Considered Options

- **Keep current CronJobs** - Kometa runs 4x/day, ImageMaid runs daily at 3am, both unattended
- **Adopt Kometa Quickstart** - Single Deployment with web UI managing both tools internally

## Decision Outcome

Chosen option: **Keep current CronJobs**, because Quickstart's design conflicts with our cluster
requirements in several ways that make it unsuitable for unattended GitOps operation.

## Consequences

- Good, because runs remain fully unattended on deterministic schedules
- Good, because rootless containers satisfy our security policy
- Good, because configs stay in git (configMapGenerator) rather than generated through a UI
- Bad, because we maintain two separate app directories instead of one
- Bad, because we miss Quickstart's maintenance-window detection (Kometa could overlap with Plex
  maintenance)

## References

- [Kometa Quickstart repository][quickstart]
- [Kometa Quickstart Docker Hub image][dockerhub]

[quickstart]: https://github.com/Kometa-Team/Quickstart
[dockerhub]: https://hub.docker.com/r/kometateam/quickstart

## Historical Context

Reasons Quickstart was rejected:

1. **Not unattended** - Runs are triggered from a web UI, not scheduled. Our CronJobs execute on
   fixed intervals without human interaction.
2. **Not rootless** - The container image runs as root (`python:3.13-slim` base, no USER directive),
   violating the cluster's pod security requirements.
3. **Runtime dependency fetching** - Quickstart downloads Kometa and ImageMaid from GitHub at first
   launch and creates virtualenvs on disk. This is fragile in a cluster environment and incompatible
   with read-only root filesystems.
4. **Config generated through UI** - Quickstart's wizard generates YAML configs interactively,
   bypassing gitops. Our configs are already authored and managed in git via configMapGenerator.
5. **No value after initial setup** - The wizard solves first-time configuration, which we completed
   long ago. The remaining features (log analytics dashboard, overlay previews) don't justify the
   trade-offs.
