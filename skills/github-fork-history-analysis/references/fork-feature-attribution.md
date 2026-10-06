# Fork Feature Attribution: Worked Pattern

Use this when a downstream fork repeatedly merges upstream and the question is whether it added functionality beyond localization or compatibility.

## Evidence sequence

1. Identify the fork point and first downstream-only commit.
2. Identify the last upstream tip fully contained by the target release.
3. Enumerate downstream-only history from the fork point to find features that were ever introduced.
4. Diff the contained upstream tip against the target release to find what still survives as downstream-specific behavior.
5. Use pickaxe and blame on each feature symbol to detect later upstream replacement or mixed implementations.
6. Inspect merge parents when blame lands on a merge commit.

## Classification examples

### Durable downstream feature

A regional service link or context-menu action is introduced downstream, remains present in the target release, and is absent from the contained upstream tip.

Report: “Added in the downstream fork and still unique at this release.”

### Historical experiment superseded by upstream

The fork introduces an IPC-based automation feature. Upstream later adds a native implementation, the fork merges it, and removes its earlier IPC path. Final files preserve only a few downstream checks or localized statuses.

Report: “The fork historically added an implementation, but the release uses an upstream-led implementation with residual downstream adaptations.” Do not call the entire final feature fork-exclusive.

### Convergent behavior

The fork independently changes proximity logic to separate horizontal distance and height. Upstream later develops similar logic. The final release contains the upstream structure plus a downstream-only dismount workaround.

Report each surviving behavior separately rather than crediting the whole subsystem to one side.

### Compatibility, not feature

A regional client exposes an array with one fewer UI argument, so the fork shifts indices. This materially restores automation but does not add a new user-facing capability.

Report: “Regional runtime compatibility patch,” not “new feature.”

## Authorship language

Repository ownership and commit authorship differ. For outside contributions merged into a fork, use:

- “added in the fork”
- “contributed by AUTHOR and merged into the fork”

Avoid “the fork owner authored” unless commit metadata and patch history support it.

## Minimal commands

```bash
git merge-base --is-ancestor UPSTREAM_TIP TARGET
git rev-list --left-right --count UPSTREAM_TIP...TARGET
git log --reverse FORK_POINT..TARGET
git diff UPSTREAM_TIP..TARGET -- relevant/path
git log --all -S'FeatureSymbol' -- relevant/path
git blame TARGET -- relevant/path
```
