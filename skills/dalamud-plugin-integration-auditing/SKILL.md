---
name: dalamud-plugin-integration-auditing
description: Audit behaviour that crosses two Dalamud plugins through IPC, exported payloads, commands, and persisted config. Use when a caller keeps creating provider-side presets or records instead of reusing them, an IPC method exists in source but subscribers cannot call it ([EzIPC] registration), ImportAndSelect/SetPreset/DeleteSelected act on different preset domains, caller logs claim success while the provider UI or config disagrees, "was this provider bug fixed in commit/tag X", or deciding which plugin owns a mutable game state (bait, presets) delegated over IPC.
---

# Dalamud Plugin Integration Auditing

Audit behaviour that crosses two Dalamud plugins through IPC, exported payloads, commands, and persisted plugin configuration. This skill owns evidence gathering, contract diagnosis, and state-ownership decisions; building and deploying either plugin is `dalamud-plugin-build`.

## Prerequisites

- Caller repository and the exact caller revision.
- Installed provider manifest and live provider config when available.
- Provider repository URL and installed or effective version.
- Read only non-secret structural configuration; credentials and unrelated user data stay out of the report.

## Procedure

1. **Define a tight lifecycle assertion.**
   For stateful integrations, test the complete lifecycle rather than a generic "IPC returned" signal:

   ```text
   find existing -> select without insertion -> import only if missing -> delete generated from same domain
   ```

   Record the exact symptom, such as the provider collection count increasing after every caller run.

2. **Establish installed provenance.**
   Read the provider's installed manifest for effective version, API level, repository URL, and download source. Resolve its source tag with `git ls-remote --tags`, clone into an OS-safe temporary directory, and record `git rev-parse HEAD`. Tag-to-SHA mapping is source provenance, not proof that the installed DLL was built unmodified from that commit.

3. **Inspect live state structurally.**
   Parse the provider config and report only relevant top-level keys, collection paths, selected IDs, counts, and non-secret names. Confirm which collection actually owns the target state, for example ordinary fishing presets versus spearfishing/AutoGig presets.

4. **Trace both IPC endpoints.**
   On the caller, locate every subscriber and call site. On the provider, verify the exact exported channel name, the registration attribute such as `[EzIPC]`, signature and nullability, the storage collection read or mutated, and whether the method acknowledges success or is `void`. A public method without provider registration is not an available IPC endpoint.

5. **Audit every lifecycle operation.**
   Read find, select, import, enable, and cleanup paths independently. A method named `ImportAndSelectPreset` may always append a new GUID; a generic `SetPreset` may operate on one preset domain only; a generic delete may clean a different collection than import populated. Fill the state table in `references/autogig-preset-lifecycle.md`.

6. **Decide game-state ownership.**
   When behaviour is delegated over IPC, decide which plugin owns each mutable game state and each created object. Trace every sibling mutation path: main update loop, arrival callbacks, gear-change hooks, recovery paths, retries, cleanup. Centralize the decision in one small pure policy function and apply it at every mutation site. If the external plugin owns the state, preserve any valid current value and run the local fallback only on an explicit uninitialized sentinel such as item ID `0`, or when the integration is disabled or unavailable. Keep the provider consumer-neutral: generic typed primitives, no consumer prefixes, timestamp parsing, ownership markers, or consumer-specific deduplication. Tested bait-ownership policy and audit pattern: `references/inter-plugin-state-ownership.md`.

7. **Compare installed, named commit, released tag, and latest main.**
   When asked whether a bug is fixed, inspect the exact commit first, then the newest released tag and current main on both caller and provider. Search for semantic changes, not only method names. Report repository, ref, and full SHA.

8. **Form a two-sided repair contract.**
   Specify the minimum provider endpoints and caller behaviour needed for idempotence. Prefer domain-specific select/delete IPC or a provider-side idempotent upsert over caller-side edits to the provider's config file. Verify that search, select, create/update, and delete all target the same provider collection through type-specific IPC, and start no create flow unless the matching cleanup capability is available.

   If another session is modifying the provider concurrently, inspect that live checkout as the source of the proposed contract before changing the caller. Match exact endpoint names and signatures, but treat uncommitted provider changes as provisional: caller compilation proves only contract wiring, not that the provider has finished building, deploying, or registering the endpoints at runtime. The caller session leaves the sibling checkout untouched.

9. **Preserve product-option semantics.**
   Distinguish "reuse an existing user preset" from "generate a temporary caller-owned preset without accumulation". A caller option may intentionally disable existing-preset reuse; in that mode one generated preset per lifecycle is correct provided import is idempotent during retries and cleanup removes the generated object. State which option must be enabled for zero creation.

10. **Verify with provider state.**
    A valid regression test runs the integration twice with the same target and asserts that the second run reuses the same provider object or GUID, the collection count does not increase, the selected state points to the expected domain, cleanup removes only caller-owned generated state, and user-owned state survives. Inspect the provider-owned collection, selected identity, and persisted config, not just log messages.

## Evidence and reporting rules

- Distinguish static source confirmation from in-game runtime confirmation.
- A caller log emitted after a `void` IPC call is not provider acknowledgement.
- Cite file paths and line numbers or exact commit refs for every contract claim.
- Inspect the source repository named by the installed manifest before conversation history or a different fork.
- Remove temporary clones and worktrees after inspection.

## Pitfalls

- Same-named concepts live in separate collections (`HookPresets.CustomPresets` versus `AutoGigConfig.Presets`).
- A method can exist for years without `[EzIPC]`; grepping only for its name creates a false positive. Prefer compiled or runtime contract checks; a regex over source text proves formatting only and is not a behavioural test.
- Import routines often regenerate GUIDs and append even when names match.
- Cleanup that selects and deletes from the ordinary domain cannot remove generated state from a specialized domain.
- Latest provider source alone is insufficient when the caller still searches or calls the wrong domain; latest caller source alone is insufficient when the provider does not export the required endpoint.
- Delegating an operation over IPC does not stop local mutation paths. A main-loop guard is incomplete while arrival, gear-change, or recovery callbacks can still overwrite the external plugin's state.
- "Fallback" is not permission to replace a valid externally selected value; gate it on an explicit unset sentinel or unavailable integration.
- Installed binary provenance never follows from a manifest version and source tag alone.

## References

- `references/autogig-preset-lifecycle.md`: state table, the GatherBuddy/AutoHook AutoGig failure pattern, provider and consumer contracts, IPC readiness, verification matrix, historical API 13 evidence, provenance wording.
- `references/inter-plugin-state-ownership.md`: tested AutoHook bait-ownership policy, behaviour matrix, and sibling mutation-path audit.

## Verification

The audit is complete only when the report answers all four questions with source evidence:

1. Where is existing state stored?
2. Which exported IPC selects it without insertion?
3. Which path imports only when missing?
4. Which domain-specific path deletes generated state without touching user-owned state?
