# Taiwan Dalamud API 13: verified regional details

Use this note as evidence for preserved Taiwan API 13 environments. Re-probe newer APIs rather than carrying these values forward by assumption.

## Client language enum

A preserved Taiwan API 13 `Dalamud.dll` exposed these relevant members as distinct values:

```text
Japanese=0
English=1
German=2
French=3
ChineseSimplified=4
ChineseTraditional=5
Korean=6
TraditionalChinese=7
```

The Taiwan runtime reported `TraditionalChinese` (`7`). Code that switched only on `ChineseTraditional` (`5`) compiled successfully but threw an unsupported-language exception at runtime. A reliable regression probe should load the target assembly, obtain the runtime member, and invoke the real language-indexing path with value `7`.

## Traditional Chinese collectable-fish dialog

A real Taiwan-client screenshot showed:

```text
確定要將下列道具收為收藏品嗎？
收藏價值：581

收藏品無法交易，也無法在市場上出售。

靈岩之劍
```

Buttons:

```text
是
否
```

Verified implications for addon automation:

- `收藏價值` is a stable, concise phrase for identifying this dialog from the supplied sample.
- `\d+` returns `581` for this exact sample because no earlier number appears.
- The full-width colon `：` and Traditional Chinese terminology should be preserved in fixtures even if the production matcher uses only `收藏價值`.
- Dialog detection and item-name extraction are separate checks. The sample confirms the visible item name `靈岩之劍`, but a fixed source such as `AtkValues[15]` still requires in-game verification.
- A focused source-backed RED test initially showed only English, Japanese, German, and French phrases; adding `收藏價值` made the supplied dialog match. This verifies recognition and numeric parsing, not the native Yes/No click.

## Traditional Chinese fishing chat samples

A GatherBuddyReborn adaptation used real Taiwan-client system messages to dispatch `ClientLanguage.TraditionalChinese` to these patterns:

```regex
在(?<FishingSpot>.+)甩出了魚線開始釣魚。
將新釣場「(?<FishingSpot>.+)」記錄到了釣魚筆記中！
開始利用上鉤的.+嘗試以小釣大
```

The undiscovered-hole marker was:

```text
未發現的釣場
```

Keep punctuation, corner brackets, and named captures exact. These samples support the observed messages only; they do not justify guessed patterns for other Chinese variants or future client versions.

## Rebaseable maintenance record example

For the official `FFXIV-CombatReborn/GatherBuddyReborn` lineage, the regional branch recorded the exact API 13 base (`f77e7a4442f76fa60ef30ac87aa201e81bf8f158`) and kept a root `AGENTS.md` pointing to `docs/TW_API13_CHANGES.md`. The maintenance note separated committed language/regex work from collectable-dialog and AutoHook ownership behavior, listed affected files, preserved real client samples, and distinguished focused verification from pending in-game checks.

This repository-level pairing is reusable:

- `AGENTS.md` carries short invariants future agents must obey.
- `docs/<regional-change-record>.md` carries session-specific evidence, behavior tables, commits/base SHA, and rebase notes.
- Before commit, remove transient status text such as “currently uncommitted” from the durable document.
- After commit, verify both paths exist, the old root-level document is absent, and the worktree is clean.

## Validation boundary

For this class of patch, report these independently:

1. Target assembly enum probe.
2. Focused localized-text regression.
3. Release build result.
4. Packaged Dalamud API level and checksum.
5. Deployment hash verification.
6. In-game plugin load, field extraction, and button action.

Do not collapse steps 1–5 into a claim that step 6 passed.
