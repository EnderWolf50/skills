# Style-fix brief

Fill every `{…}` and send the block below to an `Implementer` agent (model haiku, effort low). Only for findings that change no behaviour: naming, formatting, lint, a stray comment or debug line. A finding that changes what the code does goes to a fixer.

```markdown
Read and follow {skill}/references/rules.md first. Repository rules on top of it:
{work.rules, one bullet each}

Goal: apply exactly these findings on branch `{branch}` in worktree `{worktree}`, one commit, behaviour unchanged.

{findings: file:line and what to change, one per bullet}

1. Make each change. Done: every bullet is applied, and nothing outside them changed.
2. Run the formatter or linter the repository uses for these files, if it has one, and the tests covering the files you touched.
3. Commit as `style: {issue ref} <what>` (or `refactor:` for a rename), ending the message with `{trailer}`.

Report, as your final message: the commit SHA, each finding with done or why not, and the commands you ran with their results.
```
