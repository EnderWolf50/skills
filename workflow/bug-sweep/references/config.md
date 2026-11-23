# bug-sweep config

One TOML file per repository, on the machine only: `~/.config/bug-sweep/<remote host>/<remote path>.toml`, where host and path come from the checkout's `origin` remote (`git@git.example.com:group/app.git` reads `~/.config/bug-sweep/git.example.com/group/app.toml`). `--config <file>` on any script points elsewhere. Everything specific to a project or an employer lives here, never in the skill. Every key is optional; an unknown key or a wrong type stops the scripts with the key's name.

```toml
state_dir = ""                       # default ~/.local/state/bug-sweep/<host>/<path>: BOARD.md and triage.json

[forge]
kind = ""                            # gitlab | github; default: github for github.com, gitlab otherwise
project = ""                         # GitLab project id; default: the checkout's project (:id)
assignee = "me"                      # "me" = the user glab/gh is logged in as, or a username

[filter]
milestone = "current"                # a title, "current" (GitLab: the one active milestone covering today;
                                     # GitHub: the open milestone due soonest), or "" for none
labels_any = ["bug"]                 # at least one of these
labels_all = []                      # every one of these
exclude_labels = ["wontfix"]
exclude_authors = []
unassigned = true                    # someone else's issue is theirs; false lets a claim join its assignees

[rank]
labels = ["security", "bug"]         # earlier ranks higher; triage.json's rank overrides; then oldest first

[work]
branch = "fix/{number}-{slug}"       # {slug}: a short kebab-case summary you write
worktrees = "~/src/.wt"              # where fixer worktrees go; default: a .wt folder beside the checkout
rules = [                            # repository rules every brief carries after the shared ones
  "Run the integration tests through `make test-integration`; they share one database.",
]

[docs]                               # repository files each role reads before it starts
fixer = ["AGENTS.md", "CONTRIBUTING.md"]
verifier = ["CONTRIBUTING.md"]
opener = ["docs/merging.md"]
merger = ["docs/ci.md"]              # names the jobs a change must pass beyond the pipeline's own gate
backport = ["docs/releases.md"]

[request]
template = "Default"                 # GitLab: --template name; GitHub: path of a template file
labels = ["bug"]
milestone = "issue"                  # issue (copy it) | current | none
update = "rebase"                    # rebase | merge: how the opener brings the branch up to date
pre_push = ["make lint", "make test"]
draft = false
language = ""                        # language of the title and description; default: the repository's habit

[merge]
ask = true                           # false: a green, mergeable request merges without asking
method = "merge"                     # merge | squash | rebase, passed to merge-pr
play_jobs = []                       # GitLab manual jobs ship.py play runs, in order, as each turns manual
require_jobs = []                    # passed to merge-pr as --require-job
timeout = 14400                      # seconds ship.py play and merge-pr wait

[backport]
mode = "never"                       # never | ask (list candidates, wait) | auto
milestone = "Cycle {n}"              # pattern matched against the issue's milestone; captures {n}
branch = "release/{n}"               # the target; must exist on the remote
name = "backport/{n}-{request}"      # backport branch; {request} = the source request's number
auto_labels = ["found-in-staging"]   # an issue label that authorizes the backport without asking
```

`ship.py backport <issue>` prints one of three verdicts: no backport (with why), `candidate` (ask the user), or `authorized` (by `mode = "auto"` or an `auto_labels` label). The `docs.backport` files may add conditions of their own; they win.

## Triage file

`triage.json` in the state directory carries what you learned reading each issue. `board.py` ranks by it, warns when an issue changed after `generated_at`, and refuses a claim that shares a group with an issue someone else holds.

```json
{
  "generated_at": "2030-05-02T10:00:00+00:00",
  "issues": {
    "128": {"rank": 1, "tier": "A small and severe", "groups": ["export-csv"], "notes": "root cause in export.py:88"},
    "131": {"rank": 9, "tier": "needs a decision", "notes": "fail loudly or return nothing on an unknown name?"}
  }
}
```

A conflict group names code two fixes would both change; leave a file every fix touches (a generated stylesheet, a shared ledger) out of the groups and in `work.rules` instead.
