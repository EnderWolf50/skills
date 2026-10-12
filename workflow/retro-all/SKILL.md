---
name: retro-all
description: Cross-project retrospective over every Claude Code session on this machine, tracked in a ledger so each run reviews only new sessions.
disable-model-invocation: true
---

A **retro-all** suggests changes to the agent's environment (skills, patches, steering files, checks, tooling) from every session since the last run, across all projects. It is done when every bucket is analysed, every `open`/`watch`/`fixed` finding is re-checked for recurrence, and the ledger records the user's decisions. Call the Skill tool with `writing-for-agents` before proposing any skill or steering text.

## Ledger

`~/.claude/retro/` holds the state between runs (machine-local):

- `sessions.tsv`: `session_id<TAB>transcript_path<TAB>size_bytes<TAB>reviewed_at`. A listed session is skipped next run unless its transcript grew.
- `findings.md`: one block per finding, numbered on from the highest `F-<n>`:

  ```
  ## F-<n> <title>
  status: open | in-progress | fixed | wontfix | watch
  category: skill | patch | correction | guardrail | navigation | tool-economy | information-access
  evidence: <session-id8> <date>, ...
  fix: <PR/commit link or file>
  recheck: <the pattern in a new session that means it recurred>
  ```

## Steps

1. **Digest.** `python3 ~/.agents/skills/retro-all/scripts/digest.py` (`--all` ignores the ledger; `--help` for the rest). It scans `~/.claude/projects` and the Windows-side `/mnt/c/Users/kerati/.claude/projects`, folds worktrees into their repo, drops title-generator and security-review sub-sessions, and prints one line per bucket: `<bucket> sessions=<n> kb=<size> files=<digest files>`. Done: the output directory and the bucket lines are known.
2. **Read the ledger.** Read `findings.md` in full (absent on the first run). Done: every finding's status and `recheck` is in mind.
3. **Analyse.** Dispatch one background subagent per bucket of 20 KB or more, plus one for all smaller buckets together, each with [`references/brief.md`](references/brief.md) as its prompt and its digest paths filled in. Done: every bucket file is covered by a returned report.
4. **Re-check.** For every `open`, `watch` and `fixed` finding, search the new digests for its `recheck` pattern (`rg` over the output directory, then `scripts/user-msgs.py <session-id8>` to confirm). A recurrence of a `fixed` finding means the fix failed: reopen it with the new evidence. Done: each such finding is marked recurred (with session ids) or clean.
5. **Present** the merged candidates to the user, ranked by severity: skill and patch candidates first, then recurrences, then the rest. Each candidate carries its evidence, its proposed change, and `new` or `F-<n>`. Done: the user has decided each candidate (do, watch, wontfix).
6. **Record.** Append each new finding to `findings.md` and update the statuses the user decided; then `python3 ~/.agents/skills/retro-all/scripts/digest.py --mark <output dir>` records the digested sessions in `sessions.tsv`. Done: `findings.md` holds every candidate presented and the mark command reports the session count.
