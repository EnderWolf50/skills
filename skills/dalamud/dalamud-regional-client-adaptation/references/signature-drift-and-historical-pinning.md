# Regional signature drift and historical version pinning

Use this note when a Dalamud plugin builds and packages for the requested API but fails during construction because `SigScanner.ScanText`, `HookFromSignature`, or an infallible signature cannot find a game function.

## Diagnostic distinction

`DalamudApiLevel` proves compatibility with the Dalamud plugin API and manifest loader. It does **not** prove compatibility with the target `ffxiv_dx11.exe` machine code. Hard-coded signatures are tied to a game binary/version/region and can drift independently of the Dalamud API.

Read the exception from the inside out:

```text
KeyNotFoundException: Can't find a signature ...
→ signature scan did not match the target executable
→ hook-owning constructor throws
→ plugin constructor fails
→ Dalamud wraps it in TargetInvocationException/AggregateException
```

The wrapper exceptions are secondary. Trace the exact source line, hook symbol, constructor path, and whether the hook is mandatory or fallible.

## Evidence workflow

1. **Explain before changing anything when the user asks for diagnosis.** Treat a pasted runtime log as an investigation request unless the user explicitly asks to repair/rebuild. State that no files were changed.
2. Read the failing source line and its constructor caller.
3. Use `git blame`, `git log -S/-G`, and `git show` to identify when the signature/hook entered the branch.
4. Compare the same symbol in current upstream only as drift evidence; a newer signature is not automatically valid for an older regional client.
5. Inspect a known regional fork using its exact historical baseline, not current `main`. Prove the merge base/tag and enumerate fork-only commits.
6. Determine whether the regional fork actually changed signatures. Compare relevant file blob hashes and search fork-only history for signature constructs. Do not credit version pinning as a regional signature rewrite.
7. Correlate game-version tags and dates. If a known-working regional fork pins an earlier game release and the failing hook was added later, classify the leading hypothesis as game-binary/version-line mismatch pending an executable scan or in-game test.

## RotationSolverReborn Taiwan API 13 case

Repository lineage:

```text
cycleapple/RotationSolverReborn
└─ FFXIV-CombatReborn/RotationSolverReborn
```

The `api13-tw` branch is based exactly on official tag `7.3.5.0`:

```text
4907d03094917f4d5625fb888a6912fef174a0e4
```

Its compatibility commit is:

```text
8b9fb1d710dbc2409d9d3d574c3c751e936db4c6
Pin API13-compatible 7.3.5 build
```

That commit:

- adds an explicit `7.3.5.0` project version;
- keeps `Dalamud.NET.Sdk/13.0.0` and `DalamudPackager 13.1.0`;
- pins `Lumina.Excel` from `*` to `7.2.2`;
- does **not** change signatures, scanner behavior, hook fallibility, or exception handling.

The signature-bearing files have identical Git blob IDs between the official base and `api13-tw`, proving the fork solved reproducibility/version alignment rather than inventing Taiwan-specific signatures.

A related BossModReborn API 13 investigation found that official `7.3.8.4` included a mandatory InventoryAck hook added after the `7.3.5.0` timeframe. A Taiwan client that matches the earlier game binary can therefore build against API 13 yet fail to load the later plugin because the later machine-code signature is absent. This timeline is strong evidence, not final proof; final proof requires scanning the actual executable or an in-game load.

## Validated historical-pinning repair workflow

When the user confirms a regional fork works in the target client, treat that as runtime evidence for its **game-version line**, not evidence that the fork contains regional signatures. Correlate the fork's exact upstream tag with the failing plugin's tags and hook-introduction history.

A validated BossModReborn repair used this sequence:

1. Prove the known-working `cycleapple/RotationSolverReborn` `api13-tw` branch is based exactly on official `7.3.5.0` and does not alter signature-bearing files.
2. Verify BossModReborn official tag `7.3.5.0` still declares API 13, targets `net9.0-windows`, uses DalamudPackager 13.1.0, and predates the mandatory InventoryAck hook introduced by `75f9a969f`.
3. Before changing production state, run a temporary source-backed RED harness that fails while the later mandatory hook is present and also asserts the manifest remains API 13.
4. Move the concise regional branch (`api13`) to the exact official `7.3.5.0` tag, initialize its pinned submodule, and rerun the harness to GREEN because the post-7.3.5 mandatory hook is absent.
5. Add root `AGENTS.md` plus `docs/TW_API13_CHANGES.md` recording authoritative lineage, exact base/submodule SHAs, omitted later behavior, verification, and pending in-game checks.
6. Clean Release outputs before rebuilding the older revision, then locked-restore/build with explicit `$DALAMUD_HOME`, verify package API/version/checksum, deploy from the Release root, and hash-compare deployed files.
7. Remove the temporary harness after final verification.

This is **historical compatibility pinning**, not a signature-only repair: the later InventoryAck tracking feature is intentionally absent. Prefer it over inventing a replacement signature when a known-working regional version line exists and the failing hook entered later. If the user specifically requires the later feature, scan the actual target executable and validate the delegate ABI before considering a signature-only patch.

Validated mechanical result for the case above: BossModReborn `7.3.5.0` restored and built with API 13/.NET 9, packaged `AssemblyVersion` 7.3.5.0, and deployed with source/destination hash equality. In-game plugin construction remained a separate user reload check because the game process was not running during the build session.

## Reporting boundary

Separate these outcomes:

- **API compatibility:** restore/build/manifest API level succeeded.
- **Dependency reproducibility:** SDK and package versions are pinned.
- **Binary compatibility:** every required signature resolves in the actual regional executable.
- **Runtime success:** the plugin constructs and loads in game.

Never collapse a successful build into a runtime-compatibility claim, and never copy a newer upstream signature into an older regional branch without evidence from that target executable.