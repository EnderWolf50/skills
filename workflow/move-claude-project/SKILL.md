---
name: move-claude-project
description: Carry Claude Code sessions and memory along when a project directory moves. Use when moving or renaming a project folder, moving a project from Windows to WSL, or asked to fix or transfer the Claude Code chat history or memory of a project that moved.
---

Claude Code files a project's sessions (`*.jsonl`, per-session subdirs) and its `memory/` under `~/.claude/projects/<slug>`, where the slug is the absolute path with every non-alphanumeric character turned into `-` (`D:\Dev\florile` → `D--Dev-florile`). A moved folder gets a fresh, empty slug dir, and `claude --resume` stops listing the old sessions. Each worktree under the project has its own slug dir (`D--Dev-florile--claude-worktrees-agent-…`) and moves with it.

The script is `scripts/move_sessions.py` in this skill's directory (`~/.agents/skills/move-claude-project/scripts/move_sessions.py`; Python 3 stdlib). It finds every slug dir whose sessions ran in OLD or below it, copies it to the matching slug under NEW, and rewrites `cwd` and every other OLD path string inside the jsonl (also OLD's `D:/x` and Git Bash `/d/x` forms). Files from `/mnt/c` land as `0600` like Claude's own; same-OS copies keep their mode. Existing destination files are kept, so a rerun is safe.

| Move | Roots |
|---|---|
| Same OS | defaults (`~/.claude/projects` on both sides) |
| Windows → WSL, run in WSL | `--from-root /mnt/c/Users/kerati/.claude/projects`, OLD as a Windows path (`'D:\Dev\florile'`) |

1. **Move the folder** first (and `git worktree repair` in it when it has worktrees). A folder that is "in use" on Windows has a process holding it: a dev server, `tgrep serve`, an editor; stop that by PID. Done: NEW exists and OLD is gone, or for a Windows → WSL copy, NEW is cloned or copied.
2. **Confirm the slug.** `ls <from-root> | rg -F -- '<slug of OLD>'`. Done: the slug dir exists; when it does not, compare the listing against the path to spot the real one before going on.
3. **Dry run**: `python3 <script> OLD NEW [roots]`. Done: every source → destination pair printed is one you expect; a pair for an unrelated project sharing the prefix means its sessions recorded a cwd under OLD, so stop and ask.
4. **Apply**: the same command with `--apply`. Done: each pair reports `copied N`.
5. **Verify**: `rg -c '"cwd":"<NEW>' <to-root>/<slug of NEW>/*.jsonl` counts lines, and `claude --resume` from NEW lists the old sessions. Done: both hold.
6. **Clean up** only when the user confirms: the same command with `--cleanup`. It deletes a source dir only when every file in it has a copy. Done: the script reports `source deleted` for each pair, or what it kept.

After editing the script, `python3 <script> --self-test` must print `self-test passed`.
