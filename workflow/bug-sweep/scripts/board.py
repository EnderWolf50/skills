# /// script
# requires-python = ">=3.11"
# ///
"""The sweep's claim board. Who is fixing what lives only on the forge (the issue's assignee), so every run reads it
live; BOARD.md in the state directory is rewritten on each run and never hand-edited.

uv run board.py [--config FILE]               list: refresh, rewrite BOARD.md, print the pickable issues in rank order
uv run board.py claim <number> [--force]      assign the issue to the configured assignee after checking nobody holds it
uv run board.py release <number>              take the configured assignee off the issue

Ranking reads triage.json in the state directory when it exists (references/config.md, "Triage file"); issues it does
not list rank by the configured priority labels, then oldest first. Exit codes: 0 done, 1 error, 2 refused.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sweep import Config, Issue, Request, SweepError, forge, load_config, mentions, remote_branches, run_cli, wanted

OK, ERROR, REFUSED = 0, 1, 2
AVAILABLE = "available"


@dataclass
class Row:
    issue: Issue
    status: str
    holder: str = ""
    rank: float = float("inf")
    tier: str = ""
    groups: list[str] = field(default_factory=list)
    notes: str = ""
    triaged: bool = False
    changed: bool = False
    group_busy: list[str] = field(default_factory=list)


def load_triage(cfg: Config) -> dict:
    path = cfg.state_dir / "triage.json"
    if not path.is_file():
        return {"generated_at": "", "issues": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("generated_at", "")
    data["issues"] = {int(k): v for k, v in data.get("issues", {}).items()}
    return data


def status_of(issue: Issue, requests: list[Request], branches: list[str], in_filter: bool, me: str,
              unassigned_only: bool, sigil: str) -> tuple[str, str]:
    """(status, holder), first matching row wins."""
    if issue.state != "open":
        return f"closed by {issue.closed_by or '?'} on {issue.closed_at[:10] or '?'}", ""
    work = (f"request {sigil}{requests[0].number} open ({requests[0].author})" if requests
            else f"branch {branches[0]}, no request" if branches else "no request or branch")
    if me in issue.assignees:
        return f"mine, {work}", me
    if issue.assignees and unassigned_only:
        return f"held by {', '.join(issue.assignees)}, {work}", issue.assignees[0]
    if not in_filter:
        return "left the filter", ""
    if requests:
        return f"unassigned but request {sigil}{requests[0].number} is open ({requests[0].author})", requests[0].author
    if branches:
        return f"unassigned but branch {branches[0]} exists", "?"
    return AVAILABLE, ""


def rank_key(row: Row, priority: list[str]) -> tuple:
    by_label = min((priority.index(label) for label in row.issue.labels if label in priority), default=len(priority))
    return (row.rank, by_label, row.issue.number)


def build(cfg: Config, run, today: date) -> tuple[list[Row], str, str]:
    f = forge(cfg, run)
    me, _ = f.me()
    flt = cfg["filter"]
    milestone = flt["milestone"]
    if milestone == "current":
        milestone = f.current_milestone(today)
    triage = load_triage(cfg)
    matches = {i.number: i for i in f.issues(milestone) if wanted(i, flt, milestone)}
    rest = [n for n in triage["issues"] if n not in matches]
    issues = {**matches, **{i.number: i for i in f.issues_by_number(rest)}}
    requests, branches = f.open_requests(), remote_branches(run)
    snapshot = datetime.fromisoformat(triage["generated_at"]) if triage["generated_at"] else None
    rows = []
    for number, issue in issues.items():
        mrs = [r for r in requests if mentions(number, r.branch) or mentions(number, r.title) or mentions(number, r.body)]
        brs = [b for b in branches if mentions(number, b)]
        status, holder = status_of(issue, mrs, brs, number in matches, me, flt["unassigned"], f.sigil)
        t = triage["issues"].get(number, {})
        changed = bool(snapshot and issue.updated_at
                       and datetime.fromisoformat(issue.updated_at.replace("Z", "+00:00")) > snapshot)
        rows.append(Row(issue, status, holder, float(t.get("rank", float("inf"))), t.get("tier", ""),
                        list(t.get("groups", [])), t.get("notes", ""), number in triage["issues"], changed))
    for r in rows:
        r.group_busy = sorted({f"{o.holder} on #{o.issue.number} ({g})" for o in rows
                               if o is not r and o.holder and o.holder not in (me, r.holder)
                               for g in set(r.groups) & set(o.groups)})
    rows.sort(key=lambda r: rank_key(r, cfg["rank"]["labels"]))
    return rows, me, milestone


def cell(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def render(rows: list[Row], me: str, milestone: str, cfg: Config) -> str:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    head = ("| Rank | Issue | Status | Tier | Groups | Title | Notes |\n"
            "| --- | --- | --- | --- | --- | --- | --- |")

    def line(i: int, r: Row) -> str:
        notes = []
        if r.status == AVAILABLE and r.changed:
            notes.append("**updated after triage: re-read it**")
        if r.status == AVAILABLE and not r.triaged:
            notes.append("not triaged")
        if r.group_busy:
            notes.append("**same group in progress: " + "; ".join(r.group_busy) + "**")
        if r.notes:
            notes.append(r.notes)
        return (f"| {i} | [#{r.issue.number}]({r.issue.url}) | {cell(r.status)} | {cell(r.tier)} | {cell(', '.join(r.groups))} "
                f"| {cell(r.issue.title)} | {cell('; '.join(notes))} |")

    sections = [("Available", [r for r in rows if r.status == AVAILABLE]),
                ("In progress", [r for r in rows if r.holder]),
                ("Closed or out of the filter", [r for r in rows if r.status != AVAILABLE and not r.holder])]
    parts = [f"# Bug sweep{f': {milestone}' if milestone else ''}", "",
             f"Written by board.py at {now} for `{me}` from {cfg.file}. A snapshot: claim with "
             "`board.py claim <number>`, which re-reads the forge first.", ""]
    for title, part in sections:
        parts += [f"## {title} ({len(part)})", "", head, *(line(rows.index(r) + 1, r) for r in part), ""]
    return "\n".join(parts)


def cmd_list(cfg: Config, run, today: date) -> int:
    rows, me, milestone = build(cfg, run, today)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    board = cfg.state_dir / "BOARD.md"
    board.write_text(render(rows, me, milestone, cfg), encoding="utf-8")
    for i, r in enumerate(rows, 1):
        if r.status == AVAILABLE:
            warn = f"  [same group in progress: {'; '.join(r.group_busy)}]" if r.group_busy else ""
            fresh = "" if r.triaged else "  [not triaged]"
            print(f"{i:>3}. #{r.issue.number}  {', '.join(r.issue.labels)}  {r.issue.title}{fresh}{warn}")
    mine = " ".join(f"#{r.issue.number}" for r in rows if r.holder == me)
    print(f"\nmine: {mine or 'none'}")
    print(f"board: {board}")
    return OK


def cmd_claim(cfg: Config, run, today: date, number: int, force: bool, sleep=time.sleep) -> int:
    f = forge(cfg, run)
    me, me_id = f.me()
    rows = {r.issue.number: r for r in build(cfg, run, today)[0]}
    if number not in rows:
        issue = f.issue(number)
        rows[number] = Row(issue, AVAILABLE if issue.state == "open" and not issue.assignees else
                           f"outside the filter, held by {', '.join(issue.assignees) or 'nobody'}")
        if not force:
            print(f"#{number} is outside the filter; pass --force to claim it anyway")
            return REFUSED
    r = rows[number]
    if r.holder == me:
        print(f"#{number} is already yours")
        return OK
    if r.status != AVAILABLE:
        print(f"#{number} cannot be claimed: {r.status}")
        return REFUSED
    if r.group_busy and not force:
        print(f"#{number} touches the same code as {'; '.join(r.group_busy)}. Check with them; --force claims it anyway.")
        return REFUSED
    shared = not cfg["filter"]["unassigned"]
    f.assign(number, (f.assignee_ids(number, me) if shared else []) + [me_id])
    sleep(3)
    after = f.issue(number).assignees
    if (me not in after) if shared else (after != [me]):
        print(f"#{number} reads back assigned to {after}: someone may have claimed it at the same time")
        return REFUSED
    print(f"#{number} assigned to {me}: {r.issue.url}")
    if r.changed:
        print("note: it changed after triage; re-read it before starting")
    return OK


def cmd_release(cfg: Config, run, number: int) -> int:
    f = forge(cfg, run)
    me, _ = f.me()
    issue = f.issue(number)
    if me not in issue.assignees:
        print(f"#{number} is not assigned to {me}")
        return REFUSED
    f.assign(number, f.assignee_ids(number, me))
    print(f"#{number}: {me} removed from the assignees")
    return OK


def main(argv: list[str], run=run_cli, today: date | None = None, sleep=time.sleep) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--config", help="config file; default: from the checkout's origin remote")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("list")
    c = sub.add_parser("claim")
    c.add_argument("number", type=lambda s: int(s.lstrip("#")))
    c.add_argument("--force", action="store_true", help="claim despite a group conflict or the filter")
    r = sub.add_parser("release")
    r.add_argument("number", type=lambda s: int(s.lstrip("#")))
    args = p.parse_args(argv)
    today = today or date.today()
    try:
        cfg = load_config(run, args.config)
        if args.cmd == "claim":
            return cmd_claim(cfg, run, today, args.number, args.force, sleep)
        if args.cmd == "release":
            return cmd_release(cfg, run, args.number)
        return cmd_list(cfg, run, today)
    except SweepError as e:
        print(f"error: {e}")
        return ERROR


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
