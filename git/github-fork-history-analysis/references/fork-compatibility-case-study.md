# Nested Fork Compatibility Case Study

## Scenario

A third-level GitHub fork claimed compatibility with a regional language/client environment on a historical framework branch. The task required separating contributions across:

```text
root project
→ automation/feature fork
→ Simplified-Chinese regional fork
→ Traditional-Chinese compatibility fork
```

## Durable diagnostic pattern

### Reconstruct every parent, not only the root source

GitHub metadata exposes both `parent` (immediate upstream) and `source` (root fork network repository). Recursing through `parent` established the four-repository chain. The final fork's target branch was an old regional release plus four commits, not current `main`.

Useful proof:

```bash
git merge-base --is-ancestor BASE TARGET
git describe --tags --always TARGET
git log --reverse BASE..TARGET
```

### Fetch heads separately when fork tags collide

Adding the grandparent remote and running a broad tagged fetch encountered same-name tags pointing at different fork objects. Fetching namespaced heads completed lineage discovery without rewriting local tags:

```bash
git fetch grandparent '+refs/heads/*:refs/remotes/grandparent/*' --prune
```

Tags were then optional evidence rather than a prerequisite for branch ancestry.

### Attribute the architecture and the regional layers separately

History showed three distinct contributions:

1. The feature fork supplied navigation, auto-gather, UI parsing, and an existing four-language abstraction.
2. The regional fork extended that abstraction to Simplified Chinese, added localized game-data sheets and chat regexes, translated hardcoded UI, switched to a regional framework SDK, and patched a regional client UI argument layout.
3. The final fork extended the five-language model to Traditional Chinese, removed enum-count assumptions, tolerated unavailable Chinese sheets, and hardened IPC load order.

The first custom Simplified-Chinese commit's direct parent was the feature fork's tip. This parent relationship was stronger evidence than repository names or README claims.

### Build an end-to-end causal chain

```text
new client-language enum value
→ localized Item/PlaceName sheet lookup
→ multilingual model field
→ item/fish identification dictionary
→ user-visible feature accepts localized names
```

Then check adjacent features independently. A Traditional-Chinese data field does not imply Traditional-Chinese UI strings or chat regexes. In this case, game-data lookup worked while hardcoded UI remained Simplified Chinese and fishing chat parsing fell back to English.

### Use range-diff for a reapplied series

The final author first developed a three-commit compatibility series on one base, then reapplied it to an older regional release. Use:

```bash
git range-diff OLD_FIRST^..OLD_LAST NEW_FIRST^..NEW_LAST
```

One commit was patch-identical; two had the same intent but different hunks because the second base already contained a fifth language and different packaging metadata. Stable patch IDs alone would have missed this relationship. Matching author dates and later committer dates corroborated reapplication.

### Classify regional changes by layer

Do not collapse all changes into “server support.” Separate:

- localized data and name identification
- localized chat parsing
- hardcoded UI translation
- regional SDK/build selection
- game-client UI argument offsets
- framework/API compatibility
- dependency updates
- IPC/load-order stability
- fallback or crash avoidance

No endpoint, packet, opcode, authentication, or protocol changes were present, so “server protocol support” would have been inaccurate.

## Matching-runtime verification correction

An initial build picked newer live assemblies and failed. That did **not** prove the historical runtime was absent. A user-provided environment variable pointed to preserved matching assemblies.

The root cause was a pinned dependency project whose Windows property hardcoded the current live-install directory, overriding the intended historical location. Query the evaluated property:

```bash
dotnet msbuild dependency/dependency.csproj \
  -getProperty:DalamudLibPath \
  -getProperty:TargetFramework \
  -getProperty:Use_Dalamud_CN \
  -nologo
```

Then override non-destructively:

```bash
dotnet build Project.sln -c Release \
  -p:RestoreLockedMode=true \
  "-p:DalamudLibPath=${DALAMUD_HOME}\\"
```

The matching historical build succeeded with zero errors. This corrected two earlier conclusions:

1. The environment did contain the required old runtime.
2. A changed object-ID property emitted a deprecation warning saying it had been renamed to the original property. Therefore the patch was better classified as a regional runtime/data-lookup workaround, not a generally required API migration.

## Reporting lesson

Lead with the actual layers:

> “Client language, localized game data, regional framework SDK, client UI layout, and plugin-integration compatibility.”

State limitations explicitly: localized data support, fallback behavior, and complete UI/chat localization are different levels of support.
