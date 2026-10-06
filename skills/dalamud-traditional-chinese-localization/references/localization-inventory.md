# Dalamud Plugin Localization Inventory

Use this reference before translating a Dalamud plugin. The goal is to identify every player-visible string source while separating translation targets from parser rules, identifiers, schemas, game data, logs, and dependency-owned UI.

## Multi-pass audit

A direct search for `ImGui.Text("...")` is only the first pass. Use several passes and keep `file:line` evidence for every candidate.

### Pass 1: direct display and chat calls

Scan same-line literals passed to:

- ImGui, ImUtf8, ImRaii, table headers, buttons, inputs, tabs, context menus, and tooltips.
- Dalamud chat and plugin wrappers such as `Print`, `PrintError`, and `Communicator`.
- Notification helpers such as `Notify.Error`, `Notify.Success`, and `AddNotification`.

Classify main UI, runtime/chat, feature UI, and debug/developer UI separately.

### Pass 2: indirect display sources

Trace strings that do not appear in a display call:

- Status properties such as `AutoStatus` that are rendered elsewhere.
- `CommandInfo.HelpMessage`, command-specific help builders, and SeStringBuilder fragments.
- Constructor labels, table/filter metadata, cached labels, and strings assigned to local variables.
- Enum `ToString()` and flag-name exposure; these have no literal at the display site and need localized converters.
- `ToName()` switch expressions, patch/expansion names, size/speed names, and other display converters.
- Duration/time formatters (`Days`, `Hours`, `Minutes`, `ET`) that feed alarms, headers, and tables.
- Default format templates with placeholders.

For composed SeStrings, localize the whole sentence as a template. Do not translate individual fragments in place because Chinese word order may differ from English.

### Pass 3: repository and dependency boundaries

Inspect surfaces outside the main UI directory:

- Dalamud notification `Title`, `Content`, and `MinimizedText` fields, including multiline initializers.
- Plugin manifest name, description, punchline, tags, and alternate YAML metadata.
- Referenced source submodules and bundled UI libraries. Confirm reachability from the plugin before treating library demo/debug strings as plugin work.
- Embedded JSON/CSV and export headers.
- Exceptions that may leak through `e.ToString()` or clipboard/import error paths.
- C# UTF-8 (`u8`), multiline, interpolated, and raw string literals.

When a plugin subclasses a dependency widget (for example a filesystem selector), prefer an injectable localization provider or overrideable labels. Avoid hardcoding one regional language directly into the submodule; that increases rebase conflicts and affects other consumers.

### Pass 4: repository-differential closure

Finish with a source-wide subtraction pass instead of another display-API grep:

1. Lex all tracked C# string literals, excluding generated `bin/` and `obj/` trees.
2. Parse every documented `file:line` anchor and subtract those source locations from the literal set.
3. Score the remainder for indirect display contexts: `Name`, `Description`, `Label`, `MenuItem`, `Communicator`, `AddText`, status fields, constructor/default data, and display metadata tuples.
4. Inspect every high-signal residual. Add real candidates, and explicitly classify stable identifiers, task/debug labels, parser keys, integration tokens, generated names, and game-data fallbacks.
5. Repeat until the unexpected high-signal residual count is zero. Residuals may remain only when each belongs to a documented exclusion or to a composed template already anchored at its first fragment.

This pass catches sources that API-adjacent searches systematically miss:

- Color/theme names and descriptions returned by metadata helpers.
- Default group or preset descriptions created outside UI files.
- Dalamud context-menu item names.
- Fallback names such as `Unknown`, imported-list descriptions, and command error nouns passed into a later message builder.
- Player-facing runtime errors in non-UI state-machine files.

For persisted default names and group keys, separate a stable serialized identifier from a localized display name. Translating the persisted key in place can duplicate defaults, break lookups, or change command behavior.

## Translation boundary

Usually translate:

- Player-facing UI labels, tooltips, help, status, chat messages, and notifications.
- Display-only enum names via explicit converters.
- Long-form time/duration text.

Usually preserve or handle separately:

- ImGui `##id` and `###id`, addon names, IPC channel names, commands, file extensions, URLs, and plugin names.
- Regexes and localized game-message matchers; these are parser compatibility rules backed by client evidence, not translation resources.
- Lumina item/fish/location/weather names; use the active regional sheet rather than translating English strings.
- Stable JSON/TSV export field names unless introducing an explicitly localized display export.
- English fields used for fuzzy-search indexes, remote data compatibility, verbose logs, or upstream-debug diagnostics.
- Stack traces and internal exception details. If users can see them, add a localized outer summary while preserving the original diagnostic text.

## Output format

A useful inventory document contains:

1. Scope and scan limitations.
2. Counts by priority and source class without pretending overlapping passes are unique totals.
3. A complete `original string -> file:line` candidate list.
4. Explicit sections for dynamic enum exposure and composed messages.
5. A `translate / preserve / game-data / internal ID / external schema / dependency-owned` review state.
6. Recommended implementation order and architecture notes, but no speculative client-message translations.

## Verification

- Re-run the extraction after each pass and verify required section headings and source references exist.
- Run the repository-differential closure pass and require `unexpected high-signal = 0`; do not call the inventory final while unexplained residuals remain.
- Validate anchors semantically, not only structurally. `line <= EOF` catches broken paths but not off-by-one errors; for multiline initializers, confirm the cited line contains the documented literal or fragment. Notification property assignment and its multiline value may be on adjacent lines.
- Check that only the intended inventory file changed.
- Validate UTF-8, control characters, trailing whitespace, line count, and non-empty output. Remember that `git diff --check` ignores an untracked inventory, so run direct text checks until the file is staged.
- Recompute every summary count after late additions; table category counts must equal their actual rows.
- Keep the inventory uncommitted unless the user requested a commit.
