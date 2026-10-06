---
name: dalamud-traditional-chinese-localization
description: Localize a Dalamud plugin for Traditional Chinese (繁體中文化, 台服). Use for 幫這個插件繁中化, 盤點玩家可見英文字串, 建立繁中 localization catalog, 補命令說明/狀態/通知/tooltip, 檢查漏網字串, 區分 UI 翻譯、Lumina 名稱與 chat parser; and for Lumina item lookups that break on Traditional Chinese clients (GetRow<Item>(..., ClientLanguage.English), Language.English, 繁中服讀不到英文 Item sheet, workshop importer fails on Chinese clients).
---

# Traditional Chinese Localization for Dalamud Plugins

Inventory and implement Traditional Chinese localization while preserving runtime contracts, official upstream lineage, and regional-client evidence. Parser compatibility, game-data names, stable identifiers, and export schemas are not UI translation and stay outside the catalog. Runtime enum probing, signature failures, and addon automation belong to `dalamud-regional-client-adaptation`; restore, build, package, and deploy belong to `dalamud-plugin-build`.

## Prerequisites

- The plugin's authoritative official repository, with its base SHA recorded before regional edits.
- `DALAMUD_HOME` pointing at the target Taiwan Dalamud installation. Keep the repository's official `Dalamud.NET.Sdk`; introduce `Dalamud.CN.NET.Sdk` or `Use_Dalamud_CN` only when the target repository and environment explicitly require them.
- Real screenshots or exact chat-log text before any localized addon matcher or regex is added.
- Repository instructions read first: `AGENTS.md` and `docs/*CHANGES*.md`.

## Procedure

1. **Establish lineage and target runtime.**
   Inspect branch, remotes, status, base commit, manifest, and SDK configuration. When language enum identity matters, probe the target `Dalamud.dll`: similar enum names are not interchangeable, and a switch that compiles can still throw at runtime. Verified Taiwan API 13 values live in `~/.agents/skills/dalamud-regional-client-adaptation/references/taiwan-api13.md`; re-probe newer APIs. Done when official upstream, target API, target assemblies, and the actual runtime language member are documented.

2. **Build the translation-boundary inventory.**
   Run the multi-pass audit in `references/localization-inventory.md` across every tracked C# source, manifest, YAML metadata, embedded data, and reachable bundled UI dependency. Record each candidate as original text plus `file:line`, priority (P0 runtime errors, notifications, command output, main UI, frequent statuses; P1 feature pages, tables, filters, tooltips, context menus; P2 debug UI), source class, and one review state:
   - `translate`: player-visible UI, tooltip, status, help, chat, notification.
   - `game-data`: a localized Lumina sheet supplies the value.
   - `preserve`: command token, plugin name, URL, stable technical text.
   - `internal-id`: ImGui `##id`/`###id`, addon, callback, IPC, task label.
   - `external-schema`: persisted JSON/TSV/clipboard interchange field.
   - `dependency-owned`: unreachable library demo/debug UI or externally localized widget.

   Report per-pass counts; overlapping passes never add up to a unique total. Done when every candidate has evidence and a review state.

3. **Trace indirect and composed sources.**
   Beyond direct ImGui, chat, and notification calls, follow strings stored before rendering: status properties, constructor labels, defaults, colour and table metadata, `CommandInfo.HelpMessage`, notification fields, `ToName()` converters, enum `ToString()`, patch/hookset/size/speed names, duration formatters. Localize each composed message (interpolation, concatenation, `string.Join`, `SeStringBuilder.AddText()` fragments) as one whole-sentence template with semantic placeholders, because Chinese word order differs from English. Preserve the stable ID half of `##`/`###` labels. Done when every dynamic display path has a key, converter, formatter plan, or exclusion, and every composed message has one template boundary.

4. **Keep runtime contracts outside the catalog.**
   Localized chat regexes, addon text matchers, and fixed `AtkValues` indices are regional compatibility code backed by exact client evidence. Commands and argument tokens, IPC channels, addon/callback names, ImGui IDs, file names, URLs, plugin names, stable persisted keys, and export headers stay unchanged. Logs keep original exception details; show a localized outer summary only where users see the failure. Done when no translation key changes a parser, identifier, persisted lookup, or interchange contract.

5. **Use Lumina for game-owned names.**
   Item, fish, bait, weather, territory, fishing-spot, aetheryte, and quest names come from the target Traditional Chinese sheet, never from translated English literals or embedded JSON. Keep English fields used for fuzzy search, remote-data compatibility, or debugging. Unknown `ClientLanguage` values fail fast; catch only the expected missing-sheet exception and cache sheet availability. When a feature forces `ClientLanguage.English` or `Language.English`, or indexes rows by enumeration order, apply the row-ID adapter pattern in `references/lumina-item-mapping.md`. Done when game-owned names have an ID-backed localized source or a documented runtime gap.

6. **Design the catalog.**
   After inventory review, introduce one resource boundary such as `Loc.Get(key)` and `Loc.Format(key, args)` with English fallback, localized enum converters, and centralized time/duration formatters. Separate stable serialized keys from localized display names for defaults, groups, and presets. For reachable bundled widgets (OtterGui or ECommons style), inject localization or override labels at the plugin boundary instead of hardcoding Traditional Chinese into the shared submodule. Done when new UI text has one source of truth and explicit fallback.

7. **Implement by priority in small batches.**
   Runtime, chat, and notification text first, then main UI and config, then feature pages and shared widgets, debug UI last and only if requested. Avoid unrelated formatting or submodule churn. After each batch, build and check placeholders, newlines, stable ImGui IDs, enum converters, formatters, and English fallback. Done when the batch builds and its inventory entries are marked implemented without touching excluded contracts.

8. **Close the inventory by differential audit.**
   Subtract documented `file:line` anchors from all tracked source literals and inspect every high-signal residual near `Name`, `Description`, `Label`, `MenuItem`, status assignments, notifications, message builders, constructors, defaults, and metadata tuples. Validate anchors semantically: the cited line must contain the literal or fragment. Done only at `unexpected high-signal = 0`.

9. **Verify and document the runtime boundary.**
   Run locked restore and Release build per `dalamud-plugin-build`, then the repository text check:

   ```bash
   git -c core.whitespace=cr-at-eol diff --check
   ```

   `git diff --check` ignores an untracked inventory, so validate its UTF-8, control characters, trailing whitespace, and anchors directly before staging. For behaviour without a test suite, run a temporary harness in the OS temp directory on the exact sample and remove it afterwards. Record screenshots or messages, mechanical checks, and pending in-game actions in `docs/<regional-change-record>.md`. Done when code verification and pending runtime verification are reported separately; a native click, layout, parser, or gameplay flow passes only after an in-game test.

## Pitfalls

- A direct ImGui scan misses statuses, command help, composed SeStrings, notification fields, converters, formatters, colour metadata, defaults, context menus, and reachable dependency widgets.
- Localized Lumina names do not localize addon text matching or chat parsing.
- Translating `Default`, group names, or preset names in persisted data duplicates records or breaks lookups; localize a display name instead.
- Translating JSON/TSV headers silently breaks downstream tools.
- Translating `SeStringBuilder` fragments separately yields broken Chinese grammar.
- Build success proves compilation and packaging, not target-client layout, chat punctuation, addon clicks, or gameplay.

## References

- `references/localization-inventory.md`: the four-pass audit, translation boundary, inventory output format, and inventory verification.
- `references/lumina-item-mapping.md`: replacing forced-English Lumina lookups with a row-ID adapter; sparse `RowId` indexes; parser-name versus display-name separation.
