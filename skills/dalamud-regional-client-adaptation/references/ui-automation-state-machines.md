# Auditing regional UI automation state machines

Use this reference when a Dalamud feature combines teleportation, navmesh movement, object lookup, addon clicks, territory transitions, and an outer task queue. The AutoDuty `Retire To -> Inn` path on the preserved API 13 branch is the concrete case.

## Audit method

Trace the feature end to end rather than stopping at the UI label:

1. Locate the config flag, destination enum, defaults, and save behavior.
2. Find every scheduler entry point: before first run, between runs, final run, manual commands, and recovery paths.
3. Follow the selected destination into its helper and then into shared teleport/movement/UI helpers.
4. Record all hard-coded regional surfaces in one table: territory IDs, object Data IDs, coordinates, menu indices, addon names, and language-dependent strings.
5. Identify the actual completion predicate. Territory change, addon disappearance, movement completion, and helper stop are not interchangeable.
6. Trace retry cadence, timeout, cancellation, and what the outer task queue does after failure. A helper becoming `None` can be mistaken for success if there is no separate failure state.
7. Compare the UI's promise with scheduler gating. Check whether a setting merely controls delay/status text while the action body still runs.
8. Leave runtime checks for every native interaction; build success cannot validate object presence, option order, or successful zone entry.

## AutoDuty API 13: `Retire To -> Inn`

Relevant files in `D:\Dev\AutoDuty`:

- `AutoDuty/Windows/Config.cs`: `RetireMode` UI and `RetireLocationEnum` selector.
- `AutoDuty/Data/Enums.cs`: `RetireLocation` values.
- `AutoDuty/AutoDuty.cs`: pre-loop and between/final-loop scheduling.
- `AutoDuty/Helpers/GotoInnHelper.cs`: destination selection, NPC interaction, completion.
- `AutoDuty/Helpers/GotoHelper.cs`: duty exit, teleport, aethernet fallback, navmesh movement.
- `AutoDuty/Helpers/ActiveHelperBase.cs`: lifecycle and timeout semantics.
- `AutoDuty/Helpers/AddonHelper.cs`: addon click throttling and readiness behavior.

### Execution chain

```text
RetireMode + Inn
  -> GotoInnHelper.Invoke(current GC)
  -> choose GC city territory, inn territory, NPC Data ID, fixed coordinate
  -> GotoHelper exits duty if needed
  -> teleport to target city when territory differs
  -> vnavmesh to innkeeper coordinate
  -> interact with NPC
  -> ClickSelectString(0), ClickSelectYesno(), ClickTalk()
  -> success only when current territory equals the selected inn territory
  -> Stop() closes addons and releases the outer task wait
```

The API 13 branch maps:

| GC value | city territory | inn territory | innkeeper Data ID | target coordinate |
|---:|---:|---:|---:|---|
| 1 | 128 | 177 | 1000974 | `(15.42688, 39.99999, 12.466553)` |
| 2 | 132 | 179 | 1000102 | `(25.6627, -8, 99.74237)` |
| default/3 | 130 | 178 | 1001976 | `(28.85994, 6.999999, -80.12716)` |

The helper updates on a 50 ms throttle and has a 600,000 ms timeout. Yes/No and Talk clicks have separate 500 ms throttles. The outer queue waits for helper state to stop, but no separate success/failure result is propagated; timeout can therefore release the queue without proving that the player entered the inn.

### Regional risks and runtime matrix

Verify on the target client:

- [ ] Current GC maps to the intended city and inn territory.
- [ ] The hard-coded innkeeper Data ID resolves to the intended NPC.
- [ ] The fixed coordinate is reachable by the installed navmesh.
- [ ] `SelectString` entry index `0` is the enter-inn action; do not assume localization preserves ordering.
- [ ] Yes/No and Talk callbacks advance the intended dialogs.
- [ ] Territory IDs are unchanged and zone entry is the completion event.
- [ ] Unemployed/GC value `0` has intentional behavior; the API 13 switch falls through to the default city.
- [ ] Locked content, occupied states, missing NPCs, and unavailable teleport destinations fail visibly rather than silently timing out.
- [ ] Disabling between-loop actions actually prevents the action body. In the observed API 13 flow, `EnableBetweenLoopActions` gates delay/status setup, while a normal continuation calls `LoopTasks()` with `between=true`; treat this as a code/UI contract mismatch requiring runtime or focused verification.
- [ ] Final-loop behavior follows `ExecuteBetweenLoopActionLastLoop`.

## Design improvements when repair is requested

Prefer an explicit result model such as `Running / Succeeded / Failed / TimedOut / Cancelled` rather than using `State != Running` as success. Validate menu semantics before clicking, log the chosen territory/NPC/entry, expose a bounded retry count, and stop or report failure at the outer queue according to user-configured policy. Keep destination data separate from the state machine so regional mappings can be reviewed or overridden without rewriting control flow.
