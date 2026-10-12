---
name: dotfiles
description: Change the user's machines through the chezmoi dotfiles repo, then sync Windows and WSL. Use when installing or adding a CLI tool, skill, MCP server or Claude Code setting, editing a file under ~/.claude or ~/.config, or asked to "sync Windows and WSL" after a dotfiles pull request lands.
---

The dotfiles repo is the single source of truth for both machines: Windows (PowerShell 7, `C:\Users\kerati\.local\share\chezmoi`) and WSL (zsh, `~/.local/share/chezmoi`). Its `README.md` maps every file; the "Dotfiles" and "Tools" sections of `~/.claude/CLAUDE.md` hold the editing rules. A change lands on one OS and reaches the other only through this procedure.

## Change

1. **Look it up.** Read the current source with `git -C "$(chezmoi source-path)" fetch` and `git show origin/main:<path>`. Read `README.md`, then search `.chezmoidata/tools.toml` for the tool's name and command, `skills.toml` for the skill, and `claude.toml` for the setting or server. Done: you know whether an entry already exists and which file owns the change.
2. **Choose the shape.** A tool is a CLI entry in `tools.toml` plus, when an agent drives it, a skill in `skills.toml`. An MCP server goes in `[claude.mcp]` only when it must stay resident (semble keeps an index in memory); write that reason as a comment beside it. A Claude Code setting goes under the `claude.toml` table that matches how it merges (`set`, `merge`, `append`). Done: one file and one table named for each piece.
3. **Edit in a worktree** of the dotfiles repo on a feature branch, starting from fresh `origin/main`. Every tool entry carries an install path for **both** OSes:
   - Windows: `winget`, `scoop`, `npm`, `psgallery` or `go`.
   - Linux: `brew`, `cask` or `npm`. `run_before_install-tools.sh` installs only those three; a `go` value is Windows-only, so a Go tool needs a brew formula or a manual install noted in `after`.
   - A tool only one OS uses says so: `os = "windows"`, or a `note` naming why Linux has none.
   Done: each new or changed entry installs on both OSes, or names the OS that skips it.
4. **Check**: `python3 .github/check.py` from the worktree root (lefthook runs it on commit; CI runs it on Linux). Done: it exits 0.
5. **Ship** with the `ship` skill. The user lands it, or asks you to with `land`.

## Sync after landing

Run on **each** OS: the one you are on, then the other through the bridge below.

1. **Pull**: `git -C "$(chezmoi source-path)" pull --ff-only`. Done: source at `origin/main`.
2. **Drift**: `chezmoi status`. For each target not marked `R`, `chezmoi diff <target>`, then `chezmoi apply --force <target>`. Done: `chezmoi status` lists only `R` lines.
3. **Apply**: `chezmoi apply --no-tty </dev/null` (start it with `run_in_background`: the first install-tools run can take minutes). Done: exit 0.
4. **Verify** each tool you added or changed: `<tool> --version` (or the entry's `check` command) on both OSes. A new skill shows up in `ls ~/.agents/skills`. Done: every one answers on both OSes; a missing one is reported with the OS and the install line that failed.

### Cross-OS bridge

From WSL into Windows:

```bash
timeout 500 "/mnt/c/Program Files/PowerShell/7/pwsh.exe" -NoProfile -c 'git -C "$(chezmoi source-path)" pull --ff-only; chezmoi status'
timeout 500 "/mnt/c/Program Files/PowerShell/7/pwsh.exe" -NoProfile -c 'chezmoi apply --no-tty'
```

From Windows (Git Bash) into WSL:

```bash
MSYS_NO_PATHCONV=1 wsl.exe -e bash -lc 'chezmoi update --no-tty </dev/null'
```

`bash -lc` loads the login PATH, where chezmoi lives (`~/.local/bin`; older installs had `~/bin`). When `chezmoi` is not found, run `wsl.exe -e bash -lc 'command -v chezmoi'` and use the absolute path it prints. `chezmoi update` pulls and applies in one; run `chezmoi status` through the same bridge first when drift is possible.
