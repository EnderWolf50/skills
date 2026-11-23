# Verifier brief

Fill every `{…}` and send the block below to a fresh `CodeReviewer` agent (model opus, effort high). Give it the issue and the branch, never the fixer's report or your own reading: a verifier handed a conclusion tends to return it confirmed.

```markdown
Read and follow {skill}/references/rules.md first. You are read-only: you run tests and read code, and leave every file and commit as you found it. Repository rules on top of it:
{work.rules, one bullet each}

Goal: decide whether branch `{branch}` in worktree `{worktree}` fixes issue {issue URL} and nothing else. Read the issue with its comments (`{glab issue view <n> --comments | gh issue view <n> --comments}`) and these files: {docs.verifier}.

Decided behaviour the fix must meet:
{decided behaviour}

Check, each with evidence:
1. Red: the test commit fails without the fix. Check out the test commit in a detached worktree of your own (`git worktree add --detach <path> <test commit>`), run the new test there, keep the failing output, then remove that worktree. Done: it fails, and for the issue's reason.
2. Green: at the branch head the new test and the existing tests covering the changed code pass.
3. Behaviour: every bullet of the decided behaviour holds, and the change reaches every place the bug lives (sibling hosts, copies of the same view, every caller of the changed method).
4. Regressions: each caller of changed code keeps its behaviour unless the decided behaviour changes it.
5. Standards: the diff (`git diff origin/{default branch}...{branch}`) follows the files above.

Report, as your final message: `verdict: pass` or `verdict: findings`, then one entry per finding with file:line, `behaviour` or `style`, the concrete input that goes wrong, and what you ran to see it. Every check above appears with its evidence, a passing one included.
```
