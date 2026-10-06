# Building a family of related repositories

Use this reference when the request covers several repositories at once: "build all repositories from this plugin author", "clone and build this plugin ecosystem", "identify the main plugin, libraries, tests, and samples", "report which repositories built and which were blocked". It coordinates discovery, classification, dependency ordering, and independent builds; every Dalamud plugin in the set follows the main procedure in `SKILL.md`, and any non-Dalamud repository follows its own CI.

## Prerequisites

- Git and the required .NET SDKs installed.
- Repository owner, organization, or explicit repository list.
- GitHub credentials only when private repositories or authenticated API access are required.
- Repositories default to `D:\Dev\<repository>` unless the user requests another location.

## Procedure

1. **Enumerate the complete repository set.**

   ```bash
   gh repo list <owner> --limit 100
   gh repo view <owner>/<repo>
   ```

   Inspect READMEs when a flagship product name differs from its repository name. Done when every plausible code repository is listed with its URL and archived status.

2. **Classify every repository.**
   Assign one role: primary application/plugin, shared library, test or mock host, sample, documentation, or archived project. Exclude documentation and archived projects from the build set unless requested. Done when every discovered repository has one role and an explicit include/exclude decision.

3. **Inspect before cloning.**
   Check `D:\Dev\<repository>` before creating a new checkout. Reuse or update a clean existing checkout only after confirming its remote and branch; existing checkouts may contain user work. Done when each included repository has one safe destination.

4. **Clone the build set.**

   ```bash
   git clone --recurse-submodules <repository-url> 'D:\Dev\<repository>'
   git -C 'D:\Dev\<repository>' status --short --branch
   ```

   Done when every included repository and required submodule is available under the requested parent.

5. **Discover authoritative builds and dependencies.**
   Inspect `*.sln`, `*.slnx`, `*.csproj`, `global.json`, lock files, `Directory.*`, and `.github/workflows/*`. CI is authoritative for SDK version, bootstrap steps, environment variables, target project, configuration, and artifact path. Done when every repository has a build target and dependency position, or a documented reason why these remain unknown.

6. **Order the repositories.**
   Build shared libraries before consumers when local project or package relationships require it. Keep independent repositories independent so one failure does not prevent the others from running. Done when each included repository appears exactly once in the build order.

7. **Build and record independently.**
   For each Dalamud plugin, run `SKILL.md` steps 5 to 9 (reference root, restore/build, triage, manifest verification, deploy). For any other repository, follow its CI directly. Preserve exit code, warnings, errors, and artifact path before moving to the next repository. A failure becomes a recorded result, not a reason to skip unrelated repositories. Done when every included repository has a success, failure, or blocked status backed by tool output.

8. **Verify and report the family.**
   Check `git status --short` in every top-level repository and modified submodule. Report a compact table with repository, role, status, and artifact path, followed by prerequisites, source modifications, exclusions, and migration blockers. Done when every discovered repository is accounted for and no partial success is described as complete success.

## Pitfalls

- Name-prefix discovery misses renamed flagship projects; inspect descriptions and READMEs.
- Building every solution project can fail on mocks even when the distributable target succeeds; follow CI.
- A successful repository does not imply the whole family succeeded; report per-repository status.
