You are analysing Claude Code session digests for a cross-project retrospective. Read-only: modify no file.

Inputs:
- Your digest file(s): <DIGEST PATHS>. Each `## <timestamp> <project-dir> <session-id8>` block gives the session's cwd, turn count, tool counts, Skill invocations, error and denial counts, `U:` lines (the user's own messages, truncated, `⏎` = newline), and `ERR:` lines (tool errors). A cwd under `.claude/worktrees/agent-*` is a delegated subagent run: its `U:` line is the delegating prompt.
- Known findings: `~/.claude/retro/findings.md`. A pattern that matches a finding there is reported as a **recurrence** of `F-<n>`, never as new.
- A session's full user messages: `python3 ~/.agents/skills/retro-all/scripts/user-msgs.py <session-id8> [max-chars]`. Open a raw transcript only to confirm a pattern (`head`, `jq`, python; transcripts run to megabytes).
- Installed skills: `~/.claude/skills`, `~/.agents/skills`, and the repo's `.claude/skills` / `.agents/skills`. The user's own skills live in EnderWolf50/skills (`gh api repos/EnderWolf50/skills/contents/<path>` reads origin). Global instructions: `~/.claude/CLAUDE.md`.
- When the bucket is a repo, read its checkout from origin (`git show origin/<default>:<path>`); a local checkout may be stale.

Find, with evidence (session-id8 + date + quote or count):
1. **Skill candidates** (priority): a workflow the user spelled out as multi-step instructions in two or more sessions, or the same correction/redo cycle recurring. For each: proposed skill name (or `<skill>-patch` when it extends someone else's skill), trigger, the steps it encodes, the sessions it would have helped, and any installed skill that already covers it (then the finding is "skill X unused / insufficient because ...").
2. **Repeated corrections**: the user pushing back ("不是", "又", "我說過", "wrong", a redo). Name the standing rule or check that prevents it: mechanical → linter, hook or CI job; judgement → coding standards or a skill.
3. **Navigation, information access, tool economy**: long searches, missing information, repeated expensive or failing tool calls. A recurring `ERR:` line is an environment fix.
4. **Repo guardrails** (repo buckets only): the repo's CLAUDE.md/AGENTS.md, package scripts, CI workflows, pre-commit hooks; a missing or unwired check that relates to a mistake seen.

Done when every session block in your digest has been read and every pattern seen in two or more sessions is either reported or matched to a known finding.

Output (900 words at most): a ranked list, skill candidates first. Each item: title, category, `new` or `recurrence of F-<n>`, evidence (session ids, dates, counts), proposed change (file + what).
