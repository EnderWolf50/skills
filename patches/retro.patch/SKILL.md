---
name: retro.patch
description: "Patch for retro: check findings against the retro ledger and record them there."
disable-model-invocation: true
user-invocable: false
---

When running `retro`, the retro ledger (location, format and scripts in `~/.agents/skills/retro-all/SKILL.md`, "Ledger") carries findings across sessions:

- **Scope.** A retro over more than one project, or over all recent sessions, follows `~/.agents/skills/retro-all/SKILL.md` instead of these steps.
- **Finding the session.** A session the user names by id may live on the other side of a Windows + WSL machine: `user-msgs.py <session-id8>` searches both sides and prints its transcript path and user messages; `digest.py --session <session-id8> --all --out <dir>` digests it. Done: the transcript path is known.
- **Before analysing**, run `ledger.py index` and read `findings.md` plus the files of its live findings. A candidate matching a known finding is presented as a **recurrence** of `F-<n>` with the new evidence; a recurrence of a `fixed` finding means the fix failed.
- **After presenting** and the user deciding each candidate, create each new one with `ledger.py new <category> "<title>"` and fill in the file it prints, edit the recurred ones, run `ledger.py index`, then record the session with `digest.py --session <session-id8> --out <dir>` followed by `digest.py --mark <dir>`. Done: every candidate presented has a file, and the session has one row in `sessions.tsv`.
