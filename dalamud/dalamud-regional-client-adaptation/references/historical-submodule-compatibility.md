# Historical submodule compatibility against preserved Dalamud assemblies

Use this note when an official historical plugin base is correct for the regional game-version line, but a pinned source submodule fails to compile against the preserved target Dalamud/FFXIVClientStructs assemblies.

## Validated pattern: SortaKinda API 13

The official SortaKinda API 13 base `e5b566d79c5ec482accbc059ff68914bc71e5134` pinned:

- KamiLib `4b9b72d59b5f46dcdce0416e070ea6328738205a`
- KamiToolKit `bce6b011ae3fe7cbf4585d65f5418512083173b5`

Locked restore succeeded against a preserved Taiwan Dalamud API 13 installation, but Release compilation failed because the target FFXIVClientStructs assembly marked the `AtkTimeline.PlayAnimation(..., byte, ...)` overload as `Obsolete(..., error: true)`. The three failures were in the pinned KamiToolKit source, not SortaKinda itself.

The validated repair was deliberately narrower than advancing the entire submodule:

1. Trace the exact compiler errors into the pinned submodule.
2. Search the submodule's official history for the same API correction.
3. Confirm official commit `6b59791656d461e270a00c1e9e0e62c56ffeebc7` changed the label ID calls from `byte`/untyped literals to `ushort`.
4. Apply only the three `ushort` call-site corrections to the pinned checkout rather than moving through dozens of unrelated intervening commits.
5. Run locked Release build against explicit `$DALAMUD_HOME` and verify the API 13 manifest.
6. Record that the patch lives inside a submodule checkout and will be removed by `git submodule update --checkout` or a hard reset unless represented by an accessible submodule commit.

This preserves the historical dependency line while adopting an independently verified source-level compatibility correction. Do not generalize this into permission to copy signatures or ABI-sensitive changes from newer clients.

## Verification ordering

Any build or ad-hoc verification run can recreate `latest.zip` and change its SHA-256 because ZIP timestamps may vary. Use this order:

1. Finish all source edits.
2. Run a temporary verification script from the OS temp directory that checks the changed behavior, performs the focused Release build, and validates the packaged manifest.
3. Delete the temporary script.
4. Calculate the final package checksum and write it into maintenance documentation.
5. Deploy or re-check deployed binaries after the final build.
6. Do not rebuild again after recording the checksum unless you also recalculate and update it.

Call this an **ad-hoc focused verification**, not a green test suite. A build/package result still does not prove in-game plugin construction or regional UI behavior.