---
name: acceptance-checklist
description: Hand a finished change to the human for acceptance - a numbered checklist of what to open, do and expect, then the defect-fix loop over what they report back. Use when a pull request is ready for the user to verify, or the user asks what to check or watch out for (「我要驗收什麼」「有什麼需要特別注意」), or asks for the next step after a build or PR.
---

The user accepts the change by hand, in the running app; the checklist is their script, and every defect they report comes back as a numbered item with a final status. Write everything shown to the user in their language.

## Checklist

1. **Surfaces.** Read the diff against the base branch (`git diff <base>...HEAD`, or the pull request's files) and list every user-visible surface it changes: page, route, dialog, form, command, message, flow. Count a shared component once per surface that renders it. Done: every changed file maps to a surface or is marked internal-only.
2. **Where.** Find how the user reaches the app from the repo's own docs (`README`, `AGENTS.md`, `docs/`, `package.json` scripts, deploy config): the local dev command and URL, and the dev or preview deployment URL if one exists. When the local stack is the only way in, start it yourself (in the background) and give the URL. Done: each surface has a concrete URL or command.
3. **Items.** For each surface write one or more items: **where** (URL or command), **as whom** (role or account, when permissions differ), **do** (the action), **expect** (the visible result). Then add the edge cases this diff touches, only those:
   - mobile width (layout, overflow, hover-only affordances like tooltips)
   - empty, loading and error states (slow network, first load, a failed request shows a styled message with its detail)
   - dirty forms (unsaved-changes bar, revert back to the original clears it, save, keyboard shortcuts)
   - permissions (a role that must be refused)
   - long text, unknown or missing references, consistent wording and icons across pages
   Done: every surface from step 1 has at least one item.
4. **Hand over.** Post the checklist in chat as a numbered list, with the URL to open first. When the change has a pull request, also put it in the PR body under `## Acceptance` (`gh pr edit <n> --body-file`). Done: the user has the list and knows where to start.

## Defect loop

The user replies with defects, usually bullets plus screenshots, across several rounds.

1. **Number** each reported defect `D1, D2, …`, continuing the numbering across rounds, and echo the list back in one line each. A bullet the user marks as a separate PR or optional is still numbered.
2. **Fix** each one at its root cause; check it the way the user saw it (same page, width, account) before calling it fixed.
3. **Report** every open number with one status:
   - **fixed**: what changed, and the item to re-check
   - **needs decision**: the options and your recommendation, one line each
   - **can't reproduce**: what you tried; ask for the step or screenshot you lack
   - **deferred**: the issue or pull request it moved to (for bullets the user marked as a separate PR)
4. Repeat from step 1 on the next reply until the user accepts (「驗收完成」, approve, merge). Done: every surface has an item, and every defect number has a final status of fixed, deferred, or decided by the user.
