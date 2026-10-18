---
name: retro.patch
description: "Patch for retro: check findings against the retro ledger and record them there."
disable-model-invocation: true
user-invocable: false
---

When running `retro`, the retro ledger (location, format and scripts in `~/.agents/skills/retro-all/SKILL.md`, "Ledger") carries findings across sessions:

- **Scope.** A retro over more than one project, or over all recent sessions, follows `~/.agents/skills/retro-all/SKILL.md` instead of these steps.
- **Finding the session.** A session the user names by id may live on the other side of a Windows + WSL machine: `user-msgs.py <session-id8>` searches both sides and prints its transcript path and user messages; `digest.py --session <session-id8> --all --out <dir>` digests it. A T3 thread id instead: `t3_thread_read` gives the thread's project, its first and last activity and its parent; the session is the transcript under that project's folder whose first and last timestamps span the same range. A fork's transcript starts with its parent's history, so for a fork match its first timestamp against the parent thread's first activity. Done: the transcript path is known.
- **Complete history.** When the user asks for the session with its subagents, `condense.py <session-id8> --out <dir>` writes the session and every subagent as readable parts, spreads the subagent parts over batch lists, and counts the security reviews run from the session's checkouts and the findings that survived. Dispatch one `retro-analyst` per main part and per batch, each with `~/.agents/skills/retro-all/references/brief-full.md` filled in. Done: every part and every batch is covered by a returned report.
- **Two habitual candidates**, weighed beside the retro's own categories for every costly pattern:
  - **Script**: work the agent typed by hand twice or more, or rebuilt by copying an earlier script, becomes a script (py, js, ps1 or sh) or a small CLI in the repo that owns it; pair it with a skill only when an agent also needs to know when to reach for it.
  - **Back to docs**: a fact the agent paid for (a search, a failed try, a question to the user) goes where the next agent looks, in the repo's own conventions: its docs, an ADR, the glossary, a config file, a code comment, an AGENTS.md pointer; memory only for a fact that belongs to no repo.
  Done: each repeated sequence and each costly fact is presented as one of these, or the presentation says why neither fits.
- **Before analysing**, run `ledger.py index` and read `findings.md` plus the files of its live findings. A candidate matching a known finding is presented as a **recurrence** of `F-<n>` with the new evidence; a recurrence of a `fixed` finding means the fix failed only when the session started after its `fixed-at` (a session keeps the steering it loaded at start).
- **After presenting** and the user deciding each candidate, create each new one with `ledger.py new <category> "<title>"` and fill in the file it prints, edit the recurred ones, run `ledger.py index`, then record the session with `digest.py --session <session-id8> --out <dir>` followed by `digest.py --mark <dir>`. Done: every candidate presented has a file, and the session has one row in `sessions.tsv`.
