---
name: dalamud-plugin-build
description: Build, verify, and deploy one Dalamud plugin against a specific DALAMUD_HOME. Use for "clone and build this Dalamud plugin", "build for API 13", "find or pin the last revision before the API upgrade", "verify the latest.zip manifest", "deploy to the plugin folder", moving and consolidating a plugin checkout or worktree, or building every repository from one plugin author (multi-repo). Other Dalamud skills delegate every restore, build, package, and deploy step here.
---

# Dalamud Plugin Build

Build and package one Dalamud plugin against the intended API environment, including a historical revision when requested, then deploy the Release output to the user's plugin collection. This skill owns Dalamud reference-root selection, compatibility triage, package verification, checkout placement, and deployment. A family of related repositories from one author follows `references/multi-repo.md`, which runs this procedure per Dalamud plugin; regional-client behaviour is `dalamud-regional-client-adaptation`.

## Environment

- Windows with Git, the .NET SDK the repository declares, and `DALAMUD_HOME` pointing at the intended Dalamud installation.
- The **home repo** holds every plugin checkout at `<home>\<repository>` and lists this skill in its `skills-lock.json`. Its gitignored `.local\dalamud.json` holds `deployRoot`, the machine's plugin collection; Release outputs deploy to `<deploy-root>\<PluginName>`.
- Scripts live in this skill's directory, `${CLAUDE_SKILL_DIR}` in Claude Code; elsewhere, use the folder this SKILL.md was loaded from.
- Git Bash may rewrite `/c/Users/...` style paths when they reach native programs. Pass quoted native paths such as `'<home>\<repository>'` and confirm with `git rev-parse --show-toplevel`.

Confirm the environment first:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/find_home.py"
printf 'DALAMUD_HOME=%s\n' "$DALAMUD_HOME"
reg.exe query 'HKCU\Environment' /v DALAMUD_HOME
reg.exe query 'HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' /v DALAMUD_HOME
dotnet --info
git --version
```

`find_home.py` prints `home`, `deployRoot`, and the config path. Exit 1 means no home repo sits above this skill or the current directory: ask the user for its path and run the remaining commands from there. A null `deployRoot` means this machine has none recorded: ask the user for the plugin collection folder, then record it with `--set-deploy-root '<folder>'`. Done when both values are known.

## Procedure

1. **Choose one final checkout path.**
   Default to `<home>\<repository>` and inspect it before cloning; reuse, update, or pick another path only after seeing what is there. Done when the final path is explicit and no existing checkout will be overwritten.

2. **Clone and read the authoritative build.**

   ```bash
   git clone --recurse-submodules <repository-url> '<home>\<repository>'
   git -C '<home>\<repository>' fetch --all --tags --prune
   git -C '<home>\<repository>' status --short --branch
   ```

   Read `*.sln`, `*.slnx`, `*.csproj`, `global.json`, lock files, the plugin manifest, and `.github/workflows/*`. CI is authoritative for SDK, bootstrap, target project, configuration, and artifact path. Done when the distributable project and expected package path are known.

3. **Resolve a requested historical API revision.**

   ```bash
   git log --all -G'Dalamud.NET.Sdk|DalamudApiLevel|apiLevel|ApiLevel' --oneline -- '*.csproj' '*.json' '*.props' '*.yml' '*.yaml'
   git rev-parse <transition>^
   git show <transition>^:<project-path>
   git diff <transition>^ <transition> -- <project-path> <manifest-path>
   ```

   Find the commit that upgrades to the next API and take its first parent. Prefer an exact tag; otherwise record the full SHA. Done when project or manifest content proves the revision is the last one on the target API. For a lagging regional client the newest tag on the requested API can still be wrong: see `dalamud-regional-client-adaptation`.

4. **Select the checkout topology.**
   One maintained historical version: `git switch -c api<level> <verified-sha>` then `git submodule update --init --recursive`. Current and historical versions needed at once: keep the current checkout and add `git worktree add --detach '<home>\<repository>-api<level>' <verified-sha>`, then init its submodules. Done when every checkout has a stated purpose, branch or detached status, and verified SHA.

5. **Evaluate the actual Dalamud reference root.**
   Old projects hard-code `$(appdata)\XIVLauncher\addon\Hooks\dev\`. Probe without editing source:

   ```bash
   (
     DALAMUD_LIB_PATH="${DALAMUD_HOME}\\"
     dotnet msbuild <project.csproj> -nologo \
       "-p:DalamudLibPath=${DALAMUD_LIB_PATH}" \
       -getProperty:DalamudLibPath \
       -getProperty:TargetFramework \
       -getProperty:RestorePackagesWithLockFile
   )
   ```

   Query dependency projects and pinned submodules separately; a `HintPath` there can select another root. Done when every evaluated path points at the intended installation and the framework matches its assemblies.

6. **Restore and build the CI-selected project.**

   ```bash
   (
     DALAMUD_LIB_PATH="${DALAMUD_HOME}\\"
     dotnet restore <project.csproj> --locked-mode "-p:DalamudLibPath=${DALAMUD_LIB_PATH}" --nologo
     dotnet build <project.csproj> -c Release --no-restore "-p:DalamudLibPath=${DALAMUD_LIB_PATH}" --nologo
   )
   ```

   Build the primary project, not a solution that drags in mocks or harnesses. Done when the exit code is 0, the DLL exists, and `<project>\bin\Release\<PluginName>\latest.zip` is non-empty.

7. **Triage compatibility failures narrowly.**
   `CS1705`, missing types, or framework mismatches are evidence of a wrong reference root before they are evidence of source drift. For an unambiguous type-name collision or documented overload change, make the smallest explicit fix and leave it uncommitted unless asked. Broad service or API drift is migration work: report it separately. A pinned submodule failing against preserved assemblies has its own narrow pattern in `dalamud-regional-client-adaptation/references/historical-submodule-compatibility.md`. Done when setup failures and source incompatibilities are distinguished with evidence.

8. **Verify the package manifest.**

   ```bash
   ZIP='<project>/bin/Release/<plugin>/latest.zip'
   test -s "$ZIP"
   python -c "import zipfile,json; z=zipfile.ZipFile(r'$ZIP'); m=json.loads(z.read('<plugin>.json').decode('utf-8-sig')); assert m['DalamudApiLevel']==<level>,m; print(m['DalamudApiLevel'],m['AssemblyVersion'])"
   sha256sum "$ZIP"
   git status --short --branch
   ```

   Finish every build-producing check before recording the checksum: a later build recreates `latest.zip` with different timestamps. Done when the packaged `DalamudApiLevel` equals the request, the checksum is recorded, and every source modification is disclosed.

9. **Deploy the Release root.**

   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/deploy_release.py" \
     --release-dir '<home>\<repository>\<project>\bin\Release' \
     --plugin-name '<PluginName>' \
     --destination-root '<deploy-root>'
   ```

   The script creates the destination, copies every Release entry except the direct child named `<PluginName>` (so no `<PluginName>\<PluginName>\...` nesting), and verifies SHA-256 equality per file. It leaves unrelated or stale destination files alone; removing them is a separate, explicit decision. Done when the script reports `DEPLOYED`, `VERIFIED`, and the skipped package directory.

10. **Consolidate worktrees when one folder is wanted.**
    From a parent directory: `git worktree list --porcelain`, `git worktree remove <historical-worktree>`, `git switch -c api<level> <verified-sha>`, then `mv` into `<home>\<repository>`. Windows refuses to remove a worktree that is the current directory of a running process; change directory first. Rebuild and repeat step 8 after moving. Done when only the requested checkout remains under `<home>` with the right branch, SHA, and package.

## Pitfalls

- `DALAMUD_HOME` loses whenever an explicit `DalamudLibPath` or a dependency `HintPath` wins; trust evaluated properties, not project text.
- A successful DLL build proves nothing about API compatibility; the packaged manifest is authoritative.
- ZIP checksums differ between otherwise identical builds because of timestamps.
- A worktree depends on the primary repository's `.git`; it earns its place only while two revisions must coexist.

## References

- `references/multi-repo.md`: enumerate, classify, order, and independently build every repository from one author, reporting per-repository status.

## Verification

Run from the final checkout; package verification must pass before deployment:

```bash
git status --short --branch && git rev-parse --show-toplevel \
&& test -s '<project>/bin/Release/<plugin>/latest.zip' \
&& python -c "import zipfile,json; z=zipfile.ZipFile(r'<project>/bin/Release/<plugin>/latest.zip'); m=json.loads(z.read('<plugin>.json').decode('utf-8-sig')); assert m['DalamudApiLevel']==<level>; print('verified package',m['DalamudApiLevel'],m['AssemblyVersion'])" \
&& python "${CLAUDE_SKILL_DIR}/scripts/deploy_release.py" --release-dir '<project>/bin/Release' --plugin-name '<plugin>' --destination-root '<deploy-root>'
```
