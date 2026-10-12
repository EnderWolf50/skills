---
name: release-cli
description: Release one of the user's own Go CLIs (bump, enved, or another EnderWolf50 repo with a .goreleaser.yaml) and roll it out to Windows and WSL. Use when asked to release, tag, publish or "update doc, commit, push, tag, update env" for such a tool.
---

The repos tag `v*` and a `release` workflow runs GoReleaser on the tag push: binaries for windows / linux / darwin, `main.version` set from the tag. Read the repo's own `.goreleaser.yaml` and `.github/workflows/release.yml` before step 3 (in the checkout, or `gh api repos/EnderWolf50/<repo>/contents/<path> --jq .content | base64 -d`) in case one differs.

1. **Docs.** Update `README.md` (and any `docs/`) for every user-facing change since the last tag: `git log --oneline $(git describe --tags --abbrev=0)..HEAD`. Done: each new flag, key or command in that log appears in the docs.
2. **Commit and push** to the default branch with explicit paths. Done: `git status --short` is empty and `git log origin/HEAD..HEAD` prints nothing.
3. **Tag.** Pick the next semver from the last tag: a breaking change bumps minor while major is 0, a feature bumps minor, a fix bumps patch. `git tag vX.Y.Z && git push origin vX.Y.Z`. Done: the tag is on the remote (`git ls-remote --tags origin vX.Y.Z`).
4. **Watch the release.** Find the run with `gh run list -R EnderWolf50/<repo> --workflow release.yml -L 1 --json databaseId,headBranch`, then `gh run watch <id> -R EnderWolf50/<repo> --exit-status` with `run_in_background`, and act on its completion notice. Done: the run is green and `gh release view vX.Y.Z -R EnderWolf50/<repo>` lists the archives; on red, `gh run view <id> --log-failed` gives the cause to report.
5. **Dotfiles entry.** Find the tool in chezmoi's `.chezmoidata/tools.toml`. It pins no version, so it changes only when the install method changes (a new module path, a first brew formula). When it does, make the change through the `dotfiles` skill. Done: the entry is current, or the dotfiles pull request is open.
6. **Roll out** the new version on both OSes:
   - Windows: `$env:GOBIN = "$HOME\.local\bin"; go install <go value>@vX.Y.Z; Remove-Item Env:GOBIN` (the `go` field of the entry; same command `Show-Tools -Install` uses). From WSL, wrap it in `"/mnt/c/Program Files/PowerShell/7/pwsh.exe" -NoProfile -c '...'`.
   - WSL: the Linux install script skips `go` entries, so `GOBIN=~/.local/bin go install <go value>@vX.Y.Z`, or `gh release download vX.Y.Z -R EnderWolf50/<repo> -p '*linux_amd64*'` and unpack into `~/.local/bin`.
   Done: `<tool> --version` prints `X.Y.Z` on both OSes.
7. **Report** the release link, the version each OS prints, and the dotfiles pull request if step 5 opened one.
