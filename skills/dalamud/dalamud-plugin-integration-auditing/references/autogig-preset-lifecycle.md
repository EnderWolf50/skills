# AutoGig preset lifecycle across Dalamud IPC

Use this reference when one plugin creates, selects, reuses, or deletes another plugin's spearfishing/AutoGig presets. The durable issue is cross-plugin ownership and lifecycle symmetry, not regional text.

## Minimal state table

Fill this before proposing a fix:

| Operation | Caller code/channel | Provider registration | Provider collection | Idempotent? |
|---|---|---|---|---|
| Find existing |  | n/a or getter |  |  |
| Select existing |  |  |  |  |
| Import missing |  |  |  |  |
| Enable feature |  |  |  |  |
| Delete generated |  |  |  |  |

Then run the same target twice and compare collection count, selected GUID, and surviving user-owned entries.

## GatherBuddy / AutoHook failure pattern

The diagnosed cross-plugin failure had four independent contract mismatches:

1. **Wrong discovery collection.** GatherBuddy searched ordinary fishing `HookPresets.CustomPresets`, while spearfishing presets lived in `AutoGigConfig.Presets`.
2. **Wrong selection endpoint.** GatherBuddy subscribed to ordinary `SetPreset`. AutoHook contained `SetPresetAutogig`, but the reviewed releases did not mark it `[EzIPC]`, so its existence did not make it callable over IPC.
3. **Non-idempotent import.** `ImportAndSelectPreset` recognized an AutoGig payload and called `AutoGigConfig.AddNewPreset`, which assigned a new GUID and appended. Timestamped caller names guaranteed another entry on each miss.
4. **Wrong cleanup domain.** GatherBuddy called ordinary `SetPreset` plus `DeleteSelectedPreset`; the provider delete operated on `HookPresets.SelectedPreset`, not the AutoGig selection populated by import.

```text
search ordinary collection
-> miss existing AutoGig preset
-> import timestamp-named AHSF payload
-> append/select new GUID
-> delete ordinary selected preset
-> AutoGig entry remains; every run adds another GUID-backed preset
```

## Provider contract

Expose symmetric, typed AutoGig primitives rather than making consumers manipulate ordinary fishing endpoints:

- Select an AutoGig preset through an AutoGig-specific endpoint.
- Delete an AutoGig preset through an AutoGig-specific endpoint.
- Alternatively, an idempotent `UpsertAndSelectAutoGigPreset` keyed by stable caller ownership plus target identity.
- When the provider already has a generic query or identity API, expose it without teaching the provider any one consumer's naming convention.
- Return success/failure where practical so the consumer can avoid claiming an operation that did not occur.

Keep the provider consumer-neutral: AutoHook recognizes no prefixes such as `GBR_`, timestamps, or another plugin's ownership markers, and never deduplicates, renames, overwrites, or deletes provider-owned presets based on consumer-specific conventions. If an import/update API is added, its collision semantics are generic and provider-owned. Consumer-specific deterministic names, reuse policy, ownership tracking, and cleanup decisions belong in the consumer.

## Consumer contract

- Branch by target domain before discovery; search the correct AutoGig collection or use the provider's query IPC.
- Use a stable key, not a timestamp, when reuse is intended.
- Reuse a matching user-owned preset without renaming or deleting it.
- Track provider-issued identity for consumer-generated presets and mark user-owned versus caller-generated state.
- Select and delete through AutoGig-specific IPC only; delete only objects the consumer created.
- Make setup and cleanup idempotent so retries, reloads, and partial failures do not leak entries.
- Restore or disable plugin state separately from preset ownership; deleting a preset does not restore prior state.

When the caller has an explicit "use existing provider presets" option, test both modes separately:

- **Enabled:** an item-ID-named user preset is selected and never deleted; no generated preset is created.
- **Disabled:** generating a temporary preset may be intentional, but repeated setup must not append duplicates and cleanup must remove the caller-owned preset.

## IPC readiness

Treat provider load order separately from API mismatch:

- A temporarily unregistered endpoint must not abort consumer initialization.
- Log each unavailable optional endpoint at most once and retry after the provider becomes ready.
- Catch only the expected not-ready/unregistered condition; signature mismatches and provider exceptions propagate.
- Capability-check the complete AutoGig contract before entering a flow that will require cleanup; create no object if the matching delete path is unavailable.

## Verification matrix

Run focused tests or an ad-hoc harness for these cases:

1. No matching preset: one preset is created, selected, then deleted.
2. Matching user preset: it is selected and preserved.
3. Repeated setup: no duplicate GUID-backed entries appear.
4. Repeated cleanup: second cleanup is a safe no-op.
5. Provider loads late: consumer retries without initialization failure.
6. Provider unloads after create: consumer reports deferred or failed cleanup without claiming deletion.
7. Same display name with different payload: deterministic collision policy is applied.
8. Ordinary fishing presets remain untouched throughout AutoGig operations.

After each case, inspect the provider-owned collection, selected identity, persisted config, and consumer ownership marker, not just log messages.

## Two-session implementation

When one session changes the provider and another consumes it, inspect the provider checkout's live diff to lock exact IPC names and signatures before wiring the caller. The provider session changes provider code; the caller session only consumes the contract. Until both sides have completed their canonical builds and deployment, label the result source-level compatibility rather than runtime integration success.

## Historical API 13 evidence

At PunishXIV/AutoHook `081cab5559ea58aa9d0c68c334999a44ab0fa9c1` (`v5.0.0.23`, the last pre-API-14 revision), state IPC such as `GetPluginState`, `GetAutoStartFishing`, and `SetAutoStartFishing` existed, but the AutoGig lifecycle remained asymmetric: `SetPresetAutogig` was not registered as IPC, AutoGig import added a fresh preset, and ordinary preset deletion did not remove AutoGig entries. Treat this SHA as evidence for that historical contract only; inspect the live provider source before adapting a newer version.

## Source-provenance wording

Safe claim:

> The installed manifest reports version X and repository Y; tag X in repository Y resolves to commit Z, whose source was inspected.

This never upgrades to "the installed DLL was built from Z" without reproducible build or binary evidence.
