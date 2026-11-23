# Rules for every bug-sweep child

You are one child of a sweep: several agents fix issues of the same repository at once, each in its own worktree. These hold for every role; your brief says what your role may do beyond them.

- **Your worktree only.** Work in the worktree your brief names. The main checkout and every other worktree belong to someone else, so leave them as they are.
- **Stage by path.** `git add <path>...` with the files you changed, so another agent's leftovers never ride along; then `git diff --cached --name-only` shows exactly your files.
- **Commits.** Conventional Commits in English with a lowercase type, the issue reference your brief gives, and the trailer your brief gives as the last lines of the message.
- **Push and forge writes belong to the opener.** A fixer, verifier or style fixer hands back a local branch, and leaves the forge (requests, issue comments, labels, assignees) to the orchestrator.
- **Scripts go in files.** On Windows, a command carrying a backslash or more than one line of logic is written to a file and run by path (`python <file>`, `bash <file>`), because the shell rewrites backslashes inside quotes and heredocs.
- **Waiting.** Start a long command (a build, a test suite, a pipeline wait) in the background and wait for the harness's completion notice; it re-invokes you when the command exits.
- **Your processes, by PID.** Write each background process's PID to a file next to its output, and stop it by that PID with its children when you are done; leave nothing running and leave other agents' processes alone, whatever their image name.
- **Line endings.** Edit files in place with the Edit tool so each file keeps its own line endings; a whole-file rewrite by a script flips CRLF files to LF.
- **Smallest change the evidence justifies.** No speculative guards; a comment only for a non-obvious why.
- **Brief versus evidence.** When the evidence contradicts your brief (the bug is already fixed, the decided behaviour is impossible, the issue asks for something else), stop and report it with the evidence; the product decision is the user's.
