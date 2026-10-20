# PR and issue comments

Post with `gh pr comment <n>` or `gh issue comment <n>`, `--body-file` for more than one line. Each comment answers one question, numbers copied from output in this session. The public-repo rule in [SKILL.md](SKILL.md) holds here too, and an issue is referenced as `#<n>` or `Refs #<n>`: closing belongs to the PR body.

## Live-test evidence

```markdown
**Live test** at <short SHA>: <what was run, on what>

- <path>: <expected> → <seen> (<clip or still>)
- Not run: <path>, <why>; follow-up #<n>

Result: <passed / failed at <step>>
```

Attach each clip or still with `--attach '<file>#<alt>'`.

## Review-fix reply

```markdown
Fixed in <short SHA>: <what changed, one line>
<or: Not changed: <reason>>
```

One reply per finding, posted on its thread (`gh api repos/<owner>/<repo>/pulls/<n>/comments/<id>/replies -f body=...`).

## Status update

```markdown
**Status**: <done / in progress / blocked>

- Done: <item> (#<PR>)
- Next: <item>
- Blocked on: <who or what>, since <date>
```

On an issue a PR covers only partly, the update names what remains, so the issue's open state stays true.
