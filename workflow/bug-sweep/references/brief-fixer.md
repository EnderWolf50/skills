# Fixer brief

Fill every `{…}` and send the block below as the fixer's whole task (`Implementer` agent, model opus, effort high). `{decided behaviour}` is the target the user or triage settled, as bullets: what must happen, what must not change. `{leads}` is the triage note (root cause, files, a precedent to mirror), marked as leads to verify. A rerun after verification puts the verifier's findings under `{decided behaviour}`.

```markdown
Read and follow {skill}/references/rules.md first. Repository rules on top of it:
{work.rules, one bullet each}

Goal: fix issue {issue URL} ({one-line summary}) test-first on branch `{branch}` in worktree `{worktree}`, and hand the branch back committed and verified locally. The issue is assigned to the sweep's owner.

Setup: in `{worktree}`, confirm `git branch --show-current` prints `{branch}` and `git log -1 --oneline` is `origin/{default branch}`. Read these before writing code: {docs.fixer}. Read the issue with its comments: `{glab issue view <n> --comments | gh issue view <n> --comments}`.

Decided behaviour:
{decided behaviour}

Leads from triage (verify each before relying on it):
{leads}

Work:
1. Reproduce first: write the test that shows the bug (or the end-to-end spec, for a page), run it, keep its failing output. Done: it fails for the reason the issue describes.
2. Commit the test alone as `test: {issue ref} <what>`, then the fix as `fix: {issue ref} <what>`, so history shows red then green. End each message with `{trailer}`.
3. Run the narrowest gate the docs name for the paths you changed, plus the existing tests covering the code you changed. Done: green, or a gate you could not run with the reason.

Report, as your final message:
1. Branch, worktree, `git log --oneline origin/{default branch}..HEAD`.
2. Root cause in two sentences with file:line.
3. What changed, per file.
4. The failing-then-passing test output, verbatim, trimmed to the relevant lines.
5. Gates run and their results; gates not run and why.
6. Anything left open, including any decision you met that the brief does not settle.
```
