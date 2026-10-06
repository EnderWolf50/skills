# Inter-plugin state ownership: AutoHook bait example

## Durable lesson

When a Dalamud plugin delegates an operation to another plugin through IPC, define ownership of the underlying game state explicitly. Enabling the external plugin is not sufficient: local code may continue to mutate the same state from update loops, arrival callbacks, gear changes, retries, or repair/recovery flows.

## Tested policy

For a local gatherer delegating fishing to AutoHook, preserve AutoHook's bait choice whenever the integration is enabled, AutoHook is available, and the game reports a nonzero current bait ID.

```text
local plugin may select bait =
    integration disabled
    OR external plugin unavailable
    OR current bait ID == 0
```

Behavior matrix:

| Integration requested | External plugin available | Current bait | Local action |
|---|---:|---:|---|
| yes | yes | nonzero | Preserve current bait; do not call local selection or change-bait logic |
| yes | yes | `0` | Run local fallback selection |
| no | any | any | Preserve legacy local behavior |
| yes | no | any | Preserve legacy local behavior |

The `0` sentinel represents no usable current bait. It is the fallback trigger, not a reason to second-guess a valid nonzero selection owned by the external plugin.

## Implementation pattern

1. Extract the matrix into one small pure policy function.
2. Apply it at every mutation site, not only the primary ready-state handler.
3. Audit at least:
   - fishing ready/update loops;
   - post-teleport and post-gear-change callbacks;
   - repair, recovery, and retry paths;
   - manual command or executor paths.
4. After an unrecoverable local fallback failure, abort and return immediately so the same tick does not continue into external-plugin startup.

A session applying this pattern found two independent bait mutations: the normal ready-state path and a post-arrival gear-change callback. Guarding only the first would still overwrite AutoHook's selection once per trip.

## Focused verification

A temporary harness should compile the production pure policy and assert all four matrix rows. Also verify that every discovered mutation path calls the policy. Then run the normal Release build and package checks. Remove the temporary harness afterward.

This verification proves policy behavior and wiring; in-game testing is still required to confirm the external plugin selects bait at the expected time and the game exposes the nonzero bait ID before local fallback runs.
