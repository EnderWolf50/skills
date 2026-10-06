# Rebasing a pull request onto its target

Done: the branch is rebased and pushed, or the rebase is aborted with the conflicting files named as a conflict that needs a decision.

1. Work in the worktree that has the branch (`git worktree list`); with none, add one under the repo's `.wt/` per its `AGENTS.md`. The main checkout is shared with other sessions: never rebase, stash or reset there, and report a held `index.lock` rather than deleting it.
2. `git fetch origin && git rebase origin/<target>`. Resolve a conflict when both sides' intent can be kept (each side added different lines, or the target moved what the branch only touched in passing); keep a rebuilt or regenerated file as tool output (rerun the tool, never hand-edit it). Where both sides changed the same logic, `git rebase --abort` and stop: the conflict needs a decision, naming the files.
3. Rerun the checks the repo's `AGENTS.md` / verification doc names for the paths the resolution touched, then `git push --force-with-lease`, and re-arm auto-merge if it was armed before the push (the push clears it; arm per `~/.agents/skills/ship/references/auto-merge.md`).
