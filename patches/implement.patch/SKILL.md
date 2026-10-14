---
name: implement.patch
description: "Patch for implement: move off the default branch into a fresh worktree before the first edit."
disable-model-invocation: true
user-invocable: false
---

When running `implement`, before step one (fetching the ticket) and before any edit:

0. **Worktree.** When the current branch is the repository's default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, usually `main` or `master`), the checkout is shared and the work moves out of it: `git fetch origin`, then `git worktree add <path> -b <branch> origin/<default>`, with the path and branch naming from the repo's `AGENTS.md`/`CLAUDE.md` when it names them. Then follow the repo's own worktree setup doc if it has one (for example `docs/agents/local-dev.md`, which links `.env` into a new worktree), and work only inside the worktree from here on; "Commit your work to the current branch" means the worktree's branch. Done: `git -C <path> branch --show-current` prints the new branch, and the setup doc's steps are complete.
