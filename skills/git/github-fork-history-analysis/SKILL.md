---
name: github-fork-history-analysis
description: Trace nested GitHub forks to find the exact inherited baseline of a branch and which changes actually provide a compatibility behaviour. Use for "what did this fork change to support platform/language/version X", separating inherited changes from fork-authored ones, proving the correct merge base instead of diffing against current main, cross-fork cherry-pick equivalence (patch-id, range-diff), or whether a fork feature still survives at a release versus the merged upstream tip.
---

# GitHub Fork History Analysis

Trace nested GitHub forks, identify the exact inherited baseline of a branch, and explain which changes actually provide a compatibility behavior. Use this for questions such as “what did this fork change to support platform/language/version X?” where the visible repository is itself a fork of another fork.

## Goals

- Separate changes inherited from ancestors from changes authored in the target fork.
- Find the correct comparison base instead of blindly diffing against current `main`.
- Explain code effects from actual patches, not commit messages alone.
- Distinguish full support from graceful degradation or crash avoidance.
- Produce reproducible evidence: repository lineage, SHAs, file paths, symbols, diffs, and verification limits.

## Workflow

### 1. Resolve the repository lineage first

Query GitHub repository metadata for the target and each immediate parent:

```bash
curl -sS https://api.github.com/repos/OWNER/REPO
```

Record:

- `full_name`
- `fork`
- `default_branch`
- `parent.full_name` — immediate parent
- `source.full_name` — root of the GitHub fork network

Do not treat `source` as the immediate upstream. For nested forks, recurse through each repository’s `parent` until reaching the root. Present both the immediate-parent chain and the root source.

### 2. Clone once and add ancestor repositories as remotes

```bash
git clone https://github.com/TARGET_OWNER/REPO.git target-repo
cd target-repo
git remote add parent https://github.com/PARENT_OWNER/PARENT_REPO.git
git remote add source https://github.com/SOURCE_OWNER/SOURCE_REPO.git
git fetch --all --tags --prune
```

If there are multiple nested parents, use descriptive remote names such as `parent`, `grandparent`, and `source`.

#### Avoid cross-fork tag collisions

Several forks may publish different objects under the same tag name. A broad `git fetch --all --tags` can then abort before storing a newly added remote's branches. When ancestry is the immediate goal, fetch heads into namespaced remote refs first:

```bash
git fetch grandparent '+refs/heads/*:refs/remotes/grandparent/*' --prune
```

Fetch tags separately only when needed. Do not force-rewrite shared local tags merely to complete lineage analysis; compare remote branch SHAs or use separately named refs instead.

### 3. Find the exact branch baseline

Do not default to `target/main..target/feature`. Test likely refs and tags:

```bash
git merge-base target/feature parent/main
git rev-list --left-right --count parent/main...target/feature
git describe --tags --always target/feature
git log --graph --decorate --oneline --all --simplify-by-decoration
```

Use `git merge-base --is-ancestor BASE TARGET` to verify a candidate. Then enumerate only target-added commits:

```bash
git log --reverse --format='%H|%ad|%an|%s' --date=iso BASE..TARGET
```

A historical compatibility branch often starts from an old release tag, not today’s default branch. Comparing it against current `main` mixes later upstream development with the compatibility patch and produces misleading conclusions.

### 4. Inspect both aggregate and per-commit diffs

```bash
git diff --stat BASE..TARGET
git diff --name-status BASE..TARGET
git diff --numstat BASE..TARGET
git show --format=fuller --stat COMMIT
git show COMMIT
```

Classify every changed hunk:

- direct compatibility behavior
- API/framework migration
- dependency or lock-file update
- stability/load-order/error-handling change
- version/packaging metadata
- whitespace or line-ending noise

Never infer functionality solely from the commit title. A commit titled for a platform may contain unrelated formatting or dependency changes.

### 5. Trace inherited foundations with blame and pickaxe

When a target patch extends an existing mechanism, identify who introduced that mechanism:

```bash
git blame BASE -- path/to/file
git log --all -S'ImportantSymbol' -- path/to/file
git log --all -G'RelevantRegex' -p -- path/to/file
git show FOUNDATIONAL_COMMIT -- relevant/files
```

This is essential when a later fork adds, for example, a sixth language to a five-language system inherited from its parent. Credit and explain both layers.

For merge-introduced lines, `git blame` may point at the merge commit. Inspect the combined diff and both parents before concluding the merge authored the feature.

### 6. Detect equivalent cherry-picks across branches

Commit SHAs differ after cherry-picking or conflict resolution. Compare stable patch IDs:

```bash
git show COMMIT --pretty=format: --patch | git patch-id --stable
```

Equal patch IDs establish patch equivalence. Different IDs do not necessarily mean different intent: base-version lines, lock files, or context adjustments may alter the patch. Compare the actual hunks before deciding.

When two branches carry an ordered series that appears to have been reapplied onto different bases, use `range-diff` in addition to per-commit patch IDs:

```bash
git range-diff OLD_FIRST^..OLD_LAST NEW_FIRST^..NEW_LAST
```

This exposes which commits are exact, which were context-adjusted, and which absorbed behavior already present in the new base. Preserve author date versus committer date in the report: matching author dates with later committer dates are strong corroborating evidence of a reapplication/cherry-pick, but the diff remains authoritative.

### 7. Separate “historically added by the fork” from “still unique at the target release”

A fork can add a feature, then later merge an upstream implementation of the same feature. Answering “did this fork add functionality?” therefore requires two comparisons:

1. **Historical introduction:** inspect fork-only commits from the original fork point and identify behavior first added on that branch.
2. **Release-state uniqueness:** compare the target release against the last fully merged upstream tip, not current upstream `main`.

```bash
# Prove the upstream tip is fully contained, then count fork-side commits.
git merge-base --is-ancestor UPSTREAM_TIP TARGET
git rev-list --left-right --count UPSTREAM_TIP...TARGET

# Inspect only surviving release-state differences in relevant paths.
git diff --stat UPSTREAM_TIP..TARGET -- path/to/subsystem
git diff UPSTREAM_TIP..TARGET -- path/to/subsystem

# Determine whose implementation survives after merges and conflict resolution.
git blame TARGET -- path/to/file
git log --all -S'KeyFeatureSymbol' -- path/to/file
```

Classify each claimed fork feature as one of:

- **Durable fork-only feature:** introduced on the fork and still absent from the fully merged upstream tip.
- **Historical fork experiment:** introduced on the fork but removed later.
- **Superseded by upstream:** the fork added an early implementation, then an upstream implementation replaced most or all of it.
- **Convergent implementation:** fork and upstream independently solved the same problem; the final code may combine both histories.
- **Regional compatibility behavior:** changes runtime behavior but exists to match a regional client/data/API layout rather than provide a new user feature.
- **Presentation/QoL:** UI text or interaction changes that should not be overstated as a new subsystem.

When a commit was authored by an outside contributor and merged into the fork, say “added in the fork” rather than attributing authorship to the fork owner. Merge-heavy histories can preserve lines from both sides, so use blame plus both merge parents before deciding which implementation survives.

See `references/fork-feature-attribution.md` for a compact worked pattern covering upstream supersession, branch-only integrations, and compatibility-vs-feature classification.

### 8. Explain the runtime mechanism end to end

Build a causal chain rather than listing files:

```text
new enum/data/API value
→ model or lookup now accepts it
→ missing data is handled
→ caller no longer throws
→ feature works or degrades to a fallback
```

Explicitly distinguish:

- **Full support:** localized data/parser/behavior is implemented.
- **Fallback support:** the program remains operational but uses another language or reduced behavior.
- **Crash avoidance only:** exceptions are swallowed or unsupported paths are skipped.

Also state what did *not* change. If no networking files, endpoints, packet structures, or opcodes changed, avoid describing client-language or framework work as “server protocol support.”

### 9. Verify without overstating

Initialize pinned submodules before building:

```bash
git submodule update --init --recursive
```

For NuGet locked restore through `dotnet build`, use an MSBuild property rather than the unsupported raw switch:

```bash
dotnet build Project.sln -c Release -p:RestoreLockedMode=true
```

If a historical branch targets an old SDK/runtime, inspect declared environment variables and actual assembly metadata before assuming only the machine's current live installation is available. Then inspect **every project and pinned submodule** for properties that may override the intended runtime path.

For MSBuild-based repositories, query evaluated values instead of inferring them from top-level project files:

```bash
dotnet msbuild path/to/project.csproj \
  -getProperty:DalamudLibPath \
  -getProperty:TargetFramework \
  -getProperty:Use_Dalamud_CN \
  -nologo
```

A dependency project may hardcode a live-install path while the main project correctly follows an environment variable. If the expected historical assemblies exist, prefer a non-destructive command-line property override and rebuild:

```bash
dotnet build Project.sln -c Release \
  -p:RestoreLockedMode=true \
  "-p:DalamudLibPath=${DALAMUD_HOME}\\"
```

Report both the evaluated wrong path and the successful override. Treat deprecation warnings as evidence about the claimed patch classification: if a changed member is already an obsolete alias in the matching runtime, call it a regional behavior workaround unless the diff proves an API migration.

If no matching runtime is available after these checks, record the version mismatch and stop short of claiming either build success or code failure. Static Git analysis remains valid; runtime validation requires matching historical SDK/assemblies and, when relevant, matching data files.

## Reporting Template

1. **Executive conclusion** — one paragraph naming the true compatibility layer.
2. **Fork lineage** — immediate-parent chain plus root source.
3. **Correct baseline** — tag/SHA and proof it is an ancestor.
4. **Target-only commits** — table with SHA, purpose, and classification.
5. **Per-file mechanism** — paths, symbols, before/after behavior.
6. **Inherited foundations** — ancestor commits that made the target changes possible.
7. **Limitations** — full support versus fallback/crash avoidance.
8. **Verification** — commands run, build/runtime result, and environmental boundary.

## Pitfalls

- Diffing against current `main` instead of the branch’s historical release base.
- Reading only GitHub’s root `source` and skipping immediate parents.
- Treating a renamed fork as an unrelated repository.
- Attributing inherited code to the final fork.
- Treating “the fork historically added this” as equivalent to “the target release still has a fork-exclusive implementation”; check the last fully merged upstream tip and classify supersession or convergence.
- Attributing an outside contributor’s downstream commit to the fork owner rather than saying it was added in the fork.
- Calling a fallback parser “complete localization.”
- Describing client data/framework compatibility as server protocol support.
- Counting lock-file, line-ending, and formatting churn as functional changes.
- Declaring a branch broken because one project resolved newer live assemblies before checking historical-runtime environment variables and submodule MSBuild overrides.
- Treating a member rename as an API migration when the matching runtime reports the changed member as a deprecated alias; reclassify from build warnings and actual semantics.
- Letting cross-fork tag collisions abort branch fetching; fetch namespaced heads first and tags separately.
- Saying an IPC wrapper “retries” without confirming later invocations still call the underlying delegate.

## Verification Checklist

- [ ] Parent chain recursively confirmed from GitHub metadata.
- [ ] Correct base proven with `merge-base --is-ancestor`.
- [ ] Target-only commit list is complete and ordered.
- [ ] Aggregate changed files and per-commit hunks both inspected.
- [ ] Inherited compatibility foundations traced with history/blame.
- [ ] Historical fork additions are separated from behavior still unique against the last fully merged upstream tip.
- [ ] Features replaced by upstream or independently implemented on both sides are labeled superseded/convergent rather than fork-exclusive.
- [ ] Outside contributors merged into the fork are credited without conflating repository owner and author.
- [ ] Equivalent cross-branch patches checked with patch IDs and `range-diff` where relevant.
- [ ] Full support, fallback, and crash avoidance are clearly separated.
- [ ] Matching-runtime environment variables and evaluated dependency/submodule MSBuild paths were checked before declaring a version mismatch.
- [ ] Build claims match real command output and matching-runtime availability.

## Reference Cases

- See `references/fork-compatibility-case-study.md` for a condensed nested-fork/API-language compatibility example and the diagnostic patterns it demonstrated.
