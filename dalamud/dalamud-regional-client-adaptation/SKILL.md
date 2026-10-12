---
name: dalamud-regional-client-adaptation
description: Diagnose and adapt a Dalamud plugin that builds but fails or misbehaves on a regional client (Taiwan/台服, China, Korea). Use for "Can't find a signature" or hook failures on a regional client, ClientLanguage enum mismatches (TraditionalChinese vs ChineseTraditional), pinning a historical version for a lagging regional game line, addon or chat automation that depends on localized dialog text, and end-to-end UI automation state machines. Routes translation work to dalamud-traditional-chinese-localization, cross-plugin IPC to dalamud-plugin-integration-auditing, and build/deploy to dalamud-plugin-build.
---

# Dalamud Regional Client Adaptation

Adapt an existing Dalamud plugin to a regional client without replacing its authoritative upstream lineage or guessing regional behaviour. Four compatibility surfaces stay distinct, and each is verified against the actual regional installation or a real user-provided sample:

1. Dalamud runtime enums and services.
2. Lumina localized sheets and row availability.
3. Addon/UI text and `AtkValue` layout.
4. Chat-log wording and regex parsing.

## Routing

- Player-visible text inventory, translation catalog, Lumina item-name mapping: `dalamud-traditional-chinese-localization`.
- Behaviour delegated to another plugin over IPC, preset or game-state ownership: `dalamud-plugin-integration-auditing`.
- Clone, historical API pinning mechanics, restore, build, package verification, deployment: `dalamud-plugin-build`.
- Which fork changed what, and against which baseline: `github-fork-history-analysis`.

## Principles

- Regional support is a small, reviewable patch stack on the official upstream, never a fork substitution. Keep the official `Dalamud.NET.Sdk` unless the target environment proves another SDK is required; resolve assemblies through the target installation's `DalamudLibPath`.
- Enum identity comes from the target `Dalamud.dll`, names and numeric values both. Similar names coexist with different values.
- `DalamudApiLevel` is not a game-binary ABI guarantee. A regional client can accept an API-compatible package yet lack a signature added in a later game patch.
- Real regional samples only. A machine-translated string is never "verified client text".
- A green build proves compilation and packaging. Runtime loading, localized names, addon indices, button actions, chat parsing, and hard-coded signatures each need focused or in-game verification, reported separately.
- A pasted runtime error is a diagnosis request. Finish the root-cause and history analysis, state that no files changed, and only then propose or apply a repair.

## Procedure

1. **Establish the target environment.**
   Record client, Dalamud API level, framework, assembly root, and game patch/version line. Pass the target root explicitly during restore and build. For a historical regional client, do not stop at the newest tag carrying the requested API level: correlate known-working regional forks, game-version tags, and the dates hard-coded hooks entered the code. Signature failures and the historical-pinning workflow: `references/signature-drift-and-historical-pinning.md`.

2. **Probe runtime enums before editing a switch.**
   Load the target `Dalamud.dll` in an isolated temporary program and print every relevant enum name and value. Reproduce the failing runtime value, then test the proposed switch or indexer path against that exact value. Verified Taiwan API 13 values and samples: `references/taiwan-api13.md`.

3. **Map localized data deliberately.**
   Check whether the regional installation exposes a dedicated Lumina language sheet, a custom language enum, or only the current-client sheet. Cache optional sheet probes per data-manager lifetime; catch only the expected missing or unsupported-sheet exception; let unknown languages fail fast. Row-ID adapters for item lookups: `~/.agents/skills/dalamud-traditional-chinese-localization/references/lumina-item-mapping.md`.

4. **Capture UI and chat evidence.**
   For addon automation, obtain a screenshot plus the exact extracted text; match a stable semantic phrase rather than the whole sentence; verify any fixed `AtkValues[index]` separately. For chat parsing, require exact client messages and keep punctuation and full-width characters. When automation spans scheduling, teleport, navmesh, object lookup, addon clicks, and zone transitions, trace the whole state machine: `references/ui-automation-state-machines.md`.

5. **Verify RED then GREEN with a focused harness.**
   When the repository has no suitable test project, create a temporary harness in the OS temp directory, outside the checkout. Feed it the exact regional sample, observe the failure, apply the smallest production change, rerun to green. The final run exercises the changed behaviour against the target assemblies, then the focused Release build and packaged-manifest check. Remove the harness afterwards. Report this as **ad-hoc focused verification**, never as a green test suite.

6. **Build, package, deploy.**
   Follow `dalamud-plugin-build` steps 5 to 9. Record the final checksum only after the last build-producing step. A pinned-submodule compile failure has its own narrow repair: `references/historical-submodule-compatibility.md`.

7. **Leave a rebaseable repository record.**
   Put regional evidence and patch rationale in `docs/<regional-change-record>.md`: authoritative upstream and base SHA, exact localized samples, affected files, behaviour tables, mechanical verification, pending in-game checks. Add or update root `AGENTS.md` so future agents find the regional invariants and the note. Before committing, replace transient wording such as "currently uncommitted" with durable branch/patch language; run `git -c core.whitespace=cr-at-eol diff --check` when the repository stores CRLF; confirm a clean worktree after commit.

## Addon dialog checklist

- [ ] Exact regional dialog text came from a screenshot or log.
- [ ] The chosen phrase uniquely identifies the target dialog.
- [ ] Number parsing was tested against the exact punctuation and numeral form, and no earlier unrelated number precedes it.
- [ ] Item-name extraction was verified independently from dialog detection.
- [ ] Accept/decline thresholds come from the intended game-data field.
- [ ] The handler runs in the expected runtime state or update loop.
- [ ] Menu indices such as `SelectString[0]` still denote the intended action on the regional client.
- [ ] Native clicks were confirmed in game.

## Pitfalls

- API compatibility and game-binary signature compatibility are separate axes; a newer upstream signature proves drift, not that its bytes belong in the historical regional branch.
- A broad `catch (Exception)` hides incompatible sheets or corrupt data; a per-row probe of a missing sheet becomes an exception storm.
- Fixed `AtkValues` indices are UI-layout assumptions until confirmed at runtime.
- A helper leaving `Running` is not success. Audit timeout and cancellation paths, require an explicit success predicate such as the intended territory transition, and check what the outer task queue does after timeout.
- UI settings and scheduler behaviour drift apart: confirm an enable/disable setting gates the action body, not only its delay or status text.

## References

- `references/taiwan-api13.md`: verified Taiwan API 13 enum values, collectable-dialog and fishing-chat samples, maintenance-record example.
- `references/signature-drift-and-historical-pinning.md`: mandatory-signature failures, proving whether a regional fork changed signatures, the RotationSolverReborn and BossModReborn API 13 pinning cases.
- `references/ui-automation-state-machines.md`: end-to-end audit of scheduler, teleport, navmesh, addon, timeout, and territory-transition behaviour; the AutoDuty `Retire To -> Inn` case.
- `references/historical-submodule-compatibility.md`: narrow, upstream-validated fix inside a pinned submodule; checksum ordering.
