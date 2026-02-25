# Use NFS for SABnzbd Incomplete Downloads

- **Status:** Accepted
- **Date:** 2026-01-18
- **Decision:** Store SABnzbd incomplete downloads on NFS instead of emptyDir to eliminate
  cross-filesystem copy during post-processing

## Context and Problem Statement

SABnzbd experienced recurring crash loops when post-processing large downloads (30GB+ REMUXes).
Incomplete downloads stored on emptyDir required full file copy to NFS complete directory (Python's
`shutil.move()` falls back to `shutil.copy2()` across filesystems). This caused OOM kills from
article metadata retention during pickle deserialization and liveness probe timeouts from blocked
API threads during multi-minute file copies.

## Considered Options

- **NFS for incomplete downloads** - Same filesystem as complete directory, moves become instant
  renames
- **Generous probe thresholds + sabnzbd tuning** - Keep emptyDir, tolerate long operations
- **Both** - NFS incomplete + reasonable probe thresholds

## Decision Outcome

Chosen option: **NFS for incomplete downloads**, because it eliminates the root cause
(cross-filesystem copy) entirely. Moves become instant `rename()` syscalls regardless of file size.

Download speed decreased from local storage rates to ~56 MB/s over NFS, which is acceptable for
usenet downloads that are not latency-sensitive.

## Consequences

- Good, because post-processing completes instantly (rename vs multi-minute copy)
- Good, because OOM kills eliminated (no pickle deserialization memory spike during copy)
- Good, because liveness probe can use standard thresholds (API stays responsive)
- Bad, because download speed limited to NFS throughput (~56 MB/s)
- Bad, because download I/O now depends on NFS availability

## References

- [SABnzbd crash loop investigation][investigation]
- Commits: `880c37d` (NFS migration), `0da99ae` (re-enable liveness probe)

[investigation]: /docs/investigations/sabnzbd-crash-loop-oom-postproc-2026-01-18.md
