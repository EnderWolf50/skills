---
name: retro-patch
description: "Patch for retro: check findings against the retro ledger and record them there."
disable-model-invocation: true
user-invocable: false
---

When running `retro`, the ledger at `~/.claude/retro/` (format in `~/.agents/skills/retro-all/SKILL.md`, "Ledger") carries findings across sessions:

- **Scope.** A retro over more than one project, or over all recent sessions, follows `~/.agents/skills/retro-all/SKILL.md` instead of these steps.
- **Before analysing**, read `~/.claude/retro/findings.md`. A candidate matching a known finding is presented as a **recurrence** of `F-<n>` with the new evidence; a recurrence of a `fixed` finding means the fix failed.
- **After presenting** and the user deciding each candidate, append the new ones to `findings.md` as `F-<n>` blocks, update the statuses of recurred ones, and add the reviewed session to `sessions.tsv` (`session_id<TAB>transcript_path<TAB>size_bytes<TAB>reviewed_at`). Done: every candidate presented has a block, and the session has a row.
