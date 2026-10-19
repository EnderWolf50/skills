---
name: retro.patch
description: "Patch for retro: find sessions on either side of WSL, two more categories, delegation picks, and the retro ledger."
disable-model-invocation: true
user-invocable: false
---

When running `retro` (scripts in `~/.agents/skills/retro-all/scripts/`; the ledger and delegation picks are defined in `~/.agents/skills/retro-all/SKILL.md`):

- **Scope.** A retro over more than one project, or over all recent sessions, follows `retro-all` instead.
- **Finding the session** (step 2). A session id may live on the other side of Windows + WSL: `user-msgs.py <session-id8>` searches both and prints its transcript path, and `digest.py --session <session-id8> --all --out <dir>` digests it. For a T3 thread id, `t3_thread_read` gives its project, first and last activity, and parent; the session is the transcript in that project whose timestamps span the same range (a fork's transcript starts with its parent's history, so match its first timestamp against the parent's). Done: the transcript path is known.
- **Ledger first.** Run `ledger.py index` and read `findings.md` plus its live findings. A candidate matching one is a **recurrence** of `F-<n>` with the new evidence; a recurrence of a `fixed` finding means the fix failed only when the session started after its `fixed-at`.
- **With subagents**, when the user asks: `condense.py <session-id8> --out <dir>` splits the session and its subagents into parts and batches; dispatch one `retro-analyst` per main part and per batch, each with `~/.agents/skills/retro-all/references/brief-full.md` filled in. Done: every part and batch has a returned report.
- **Two more categories** for step 3:
  - **Script**: did the agent type the same work by hand twice, or rebuild it from an earlier script? Make it a script or small CLI in the repo that owns it, plus a skill only when an agent must know when to reach for it. _Use when_ a sequence repeated.
  - **Back to docs**: did the agent pay for a fact (a search, a failed try, a question to the user)? Put it where the next agent looks, in the repo's conventions (docs, ADR, glossary, config, code comment, AGENTS.md pointer); memory only for a fact that belongs to no repo. _Use when_ a fact cost turns.
- **Who runs it.** Each candidate that hands work to an agent carries a pick per **Delegation picks**.
- **After the user decides**, `ledger.py new <category> "<title>"` for each new candidate and fill in the file it prints, edit the recurred ones, run `ledger.py index`, then `digest.py --session <session-id8> --out <dir>` and `digest.py --mark <dir>`. Done: every presented candidate has a ledger file, each delegating one carries its pick, and the session has one row in `sessions.tsv`.
