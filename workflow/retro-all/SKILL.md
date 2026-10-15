---
name: retro-all
description: Cross-project retrospective over every Claude Code session on this machine, tracked in a ledger so each run reviews only new sessions.
disable-model-invocation: true
---

A **retro-all** suggests changes to the agent's environment (skills, patches, steering files, checks, tooling) from every session since the last run, across all projects. It is done when every bucket is analysed, every live finding is re-checked for recurrence, and the ledger records the user's decisions. Call the Skill tool with `writing-for-agents` before proposing any skill or steering text.

Scripts live in `~/.agents/skills/retro-all/scripts/`; run them with `python3` (`python` on Windows), each takes `--help`.

## Ledger

One ledger per machine holds the state between runs: `~/.claude/retro/`, on the Windows side of a Windows + WSL machine (`/mnt/c/Users/<user>/.claude/retro/` from WSL), so a run from either side reads and writes the same files. `ledger.py index` prints its path. A second ledger left on the WSL side by an older version is merged in once with `ledger.py import <its path>`.

- `sessions.tsv`: `session_id<TAB>transcript_path<TAB>size_bytes<TAB>reviewed_at`, written by `digest.py --mark` (and merged by `ledger.py import`). A listed session is skipped next run unless its transcript grew, and a grown one is digested from the recorded size on.
- `findings/F-<n>.md`: one file per finding. A finding is never deleted: a dropped one becomes `wontfix`, a duplicate becomes `wontfix` with `fix: duplicate of F-<m>`.

  ```
  # F-<n> <title>
  status: open | in-progress | fixed | wontfix | watch
  category: skill | patch | correction | guardrail | navigation | tool-economy | information-access
  evidence: <session-id8> <date> (<what happened>), ...
  fix: <PR/MR link, or repo + branch + commit while unpublished>
  recheck: <the pattern in a new session that means it recurred>
  recheck-rg: <optional Python regex over the agent's tool-call inputs (commands, scripts, edited paths) that flags that pattern>
  fixed-at: <UTC ISO time the fix took effect on this machine: merged, and applied or pulled where it lives>
  ```

  Free notes may follow the fields.
- `findings.md`: the index, generated. `ledger.py index` rewrites it from `findings/` and prints the next free id.

## Steps

1. **Digest.** `digest.py` (`--all` ignores the ledger). It scans the sessions of both sides of a Windows + WSL machine from either side (`\\wsl.localhost\<distro>` from Windows; `/mnt/c` from WSL), folds worktrees into their repo, drops title-generator and security-review sub-sessions, and prints one line per bucket: `<bucket> sessions=<n> kb=<size> files=<digest files>`. Done: the output directory and the bucket lines are known.
2. **Read the ledger.** `ledger.py index`, then read `findings.md` and the `findings/F-<n>.md` of every `open`, `in-progress`, `watch` and `fixed` finding. Done: every live finding's status and `recheck` is in mind.
3. **Analyse.** Dispatch one background subagent (`subagent_type: retro-analyst`; `general-purpose` when that type is not available) per bucket of 20 KB or more, plus one for all smaller buckets together, each with [`references/brief.md`](references/brief.md) as its prompt and its digest paths and the ledger path filled in. Done: every bucket file is covered by a returned report.
4. **Re-check.** `ledger.py recheck <output dir>` lists each live finding whose `recheck-rg` matched a new session; confirm each hit with `user-msgs.py <session-id8>` or the transcript. A live finding without `recheck-rg` is re-checked by hand against the digests, and gets a `recheck-rg` when its pattern is mechanical. A session keeps the steering it loaded when it started, so only a session started after a `fixed` finding's `fixed-at` can show the fix failed: recheck leaves out earlier ones, and a hand recheck compares the session's first timestamp the same way. Such a recurrence reopens the finding with the new evidence. Then, for every `in-progress` finding, check whether its fix landed (`gh pr view <url> --json state`, `glab mr view <url>`, or `git branch -r --contains <sha>`) and took effect here (`chezmoi apply` or `npx -y skills update -g -y` done, the repo pulled); then it is `fixed`, with `fixed-at` set to that moment. Done: each live finding is marked recurred (with session ids) or clean, and each `in-progress` one landed or still pending.
5. **Present** the merged candidates to the user, ranked by severity: skill and patch candidates first, then recurrences, then the rest. Each candidate carries its evidence, its proposed change, and `new` or `F-<n>`. Done: the user has decided each candidate (do, watch, wontfix).
6. **Record.** Create each new finding with `ledger.py new <category> "<title>"` (it claims the id, so a concurrent retro cannot take the same one) and fill in the file it prints; edit the files of the findings whose status or evidence changed, run `ledger.py index`, then `digest.py --mark <output dir>`. Done: every candidate presented has a file, the index lists it, and the mark command reports the session count.
