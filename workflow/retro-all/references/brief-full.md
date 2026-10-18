You are analysing part of one Claude Code session's complete history (the session and its subagents) for a retrospective that improves the agent's **environment** (skills, steering files, checks, tooling), not the code. Read-only: modify no file.

Inputs are condensed transcripts written by `condense.py`. Line formats: `[MM-DDTHH:MM] U:` a user message (in a subagent file the first `U:` is the delegating prompt), `A:` assistant text, `T <tool>: <input>` a tool call, `ERR:` a failed or denied tool result, `BIG-RESULT` a tool result over 25k chars. Each file starts with `tools={...}` counts. Your files: <FILES>. Read every line of every file (Read with offset and limit; the files are large).

Context you may consult:
- Steering: `~/.claude/CLAUDE.md`, the repo's `AGENTS.md` / `CLAUDE.md` and the docs they point at, the project's memory folder.
- Repo checks: `git -C <repo> show origin/<default>:<path>` for CI workflows, package and build configs, pre-commit hooks.
- Installed skills: `~/.claude/skills`, `~/.agents/skills`, the repo's `.claude/skills` / `.agents/skills`.
- Known findings: the ledger's `findings.md` and `findings/F-<n>.md` (<LEDGER PATH>); a pattern matching one is a **recurrence** of `F-<n>`.
- The raw transcript, only to confirm a pattern: <TRANSCRIPT> (use python or rg, never Read it whole).

Find **every** instance, with evidence (file + timestamp + short quote or count):
1. **Skill candidates**: a workflow the user spelled out as multi-step instructions, or a correction/redo cycle that recurs. Proposed skill name (or `<skill>.patch` for someone else's skill), trigger, steps, and any installed skill that already covers it.
2. **User corrections and pushback** ("不是", "又", "我說過", "為什麼", a redo, a reversal). What the agent did wrong, and the standing rule or check that prevents it (mechanical → linter, hook or CI job; judgement → coding standards or a skill).
3. **Agent mistakes the user did not catch**: wrong claims, broken commits, skipped tests, steps claimed done but not done, CI failures, reverted work, wasted live runs.
4. **Navigation, information access, tool economy**: long searches, missing information, repeated or failing tool calls (cluster the `ERR:` lines by cause), oversized outputs, polling loops, delegations that returned little, subagents redoing each other's work.
5. **Delegation quality** (subagent files especially): was the brief complete and its premises true? Did the subagent stall, ask for missing context, go off scope, break its worktree, or report falsely? Did the parent verify?
6. **Steering no-ops or conflicts**: an instruction that was ignored, contradicted, or cost turns.
7. **Script candidates**: work typed by hand twice or more, or rebuilt by copying an earlier script; propose a script (py, js, ps1 or sh) or small CLI in the repo that owns it, with a skill only when an agent also needs to know when to reach for it.
8. **Back to docs**: a fact paid for with a search, a failed try or a question to the user; propose its home in the repo's conventions (doc, ADR, glossary, config, code comment, AGENTS.md pointer), memory only for a fact that belongs to no repo.

Done when every line of your files is read and every pattern is reported, one-off ones marked `x1`.

Output (1,500 words at most), a ranked list, most severe first. Each item: title, category (skill | patch | correction | guardrail | navigation | tool-economy | information-access | delegation | steering | script | docs), severity (high/med/low), evidence, proposed change (file + what), and a `recheck` pattern plus a `recheck-rg` Python regex over tool-call inputs when the pattern is mechanical. Write in English.
