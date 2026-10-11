---
name: compare-alternatives
description: Compare candidate tools, libraries or apps side by side for the user and recommend one. Use when asked for alternatives to X, "X vs Y vs Z", whether a tool beats what the user already uses, or which project to pick by GitHub stars and community reception.
---

The answer is a chat reply: one table and a recommendation, in the user's language. Every cell carries a number or a fact from a source fetched this session.

1. **Candidates.** Take the ones the user named, add the user's current tool when one fills the same role (`.chezmoidata/tools.toml` in the dotfiles repo, `~/.claude/settings.json` plugins, `~/.agents/skills`), and fill up to five with the most-starred ones found through `tinyfish search query` (the `use-tinyfish` skill). Done: each candidate has a GitHub repo, or is marked closed-source.
2. **Fetch** each column below per candidate. Done: every cell is filled, or reads `n/a` with the reason (no public repo, API limit).
3. **Table**: one row per candidate, the columns in the order below, sorted by stars. Mark the user's current tool.
4. **Recommend** one pick in two or three sentences, tied to the user's setup (Windows + WSL, CLI plus skill over MCP server, installable through chezmoi), and name the runner-up with the condition that would make it the pick. Done: the reply holds the table, the pick, and the source links behind the sentiment column.

## Columns

| Column | How |
|---|---|
| Stars | `gh api repos/<o>/<r> --jq .stargazers_count` |
| Stars in the last ~90 days | `curl -s 'https://api.ossinsight.io/v1/repos/<o>/<r>/stargazers/history/?per=month' \| jq -r '.data.rows[-4:][] \| "\(.date) \(.stargazers)"'`: the last row minus the first of those four. The series is a running count from GH Archive that starts below the real total, so use only its differences. GitHub's own stargazers list answers 404 |
| Last commit | `gh api repos/<o>/<r>/commits?per_page=1 --jq '.[0].commit.committer.date'` |
| Open issues | `gh api repos/<o>/<r> --jq .open_issues_count` (counts pull requests too) and the trend: `gh search issues --repo <o>/<r> --created '>=<90 days ago>' --limit 1000 --json state --jq 'group_by(.state) \| map({(.[0].state): length}) \| add'` (opened in 90 days, by current state) |
| License | `gh api repos/<o>/<r> --jq .license.spdx_id` |
| Windows + WSL | release assets (`gh release view -R <o>/<r> --json assets`) and the README install section: native on each, or how |
| chezmoi install | the `tools.toml` fields it would get: `winget` / `scoop` / `npm` / `go` on Windows, `brew` / `cask` / `npm` on Linux. Name the package IDs found, or "manual" |
| Sentiment | `tinyfish search query` for Hacker News, Reddit and GitHub discussions on the project; one line summing them up with two or three links |
