# /// script
# requires-python = ">=3.11"
# ///
"""Shared by board.py and ship.py: the machine-local config and a small GitLab/GitHub layer over glab and gh.

The config for a checkout lives at ~/.config/bug-sweep/<remote host>/<remote path>.toml, found from the
checkout's origin remote; references/config.md documents its keys.
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import quote

CONFIG_ROOT = Path("~/.config/bug-sweep")
STATE_ROOT = Path("~/.local/state/bug-sweep")
HTTP_STATUS = re.compile(r"HTTP (\d{3})")


class SweepError(Exception):
    pass


def run_cli(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


def call(run, cmd: list[str]):
    """Run a glab/gh command and parse its JSON (several concatenated pages become one list)."""
    code, out, err = run(cmd)
    if code != 0:
        status = HTTP_STATUS.search(err)
        raise SweepError(f"{' '.join(cmd[:4])} failed{f' (HTTP {status.group(1)})' if status else ''}: {(err or out).strip()}")
    text = out.strip()
    if not text:
        return None
    decoder, pos, parts = json.JSONDecoder(), 0, []
    while pos < len(text):
        value, pos = decoder.raw_decode(text, pos)
        parts.append(value)
        while pos < len(text) and text[pos].isspace():
            pos += 1
    if len(parts) == 1:
        return parts[0]
    return [item for part in parts for item in (part if isinstance(part, list) else [part])]


# ---------------------------------------------------------------- remote and config

def parse_remote(url: str) -> tuple[str, str]:
    """(host, path) of a git remote URL, path without .git: git@h:g/p.git, ssh://git@h:22/g/p, https://h/g/p.git."""
    url = url.strip()
    m = re.match(r"^[a-z+]+://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url) \
        or re.match(r"^(?:[^@/]+@)?([^/:]+):(.+?)(?:\.git)?/?$", url)
    if not m:
        raise SweepError(f"cannot read host and path from remote {url!r}")
    return m.group(1).lower(), m.group(2)


def config_path(host: str, path: str) -> Path:
    return (CONFIG_ROOT / host / f"{path}.toml").expanduser()


DEFAULTS = {
    "forge": {"kind": "", "project": "", "assignee": "me"},
    "filter": {"milestone": "", "labels_any": [], "labels_all": [], "exclude_labels": [], "exclude_authors": [],
               "unassigned": True},
    "rank": {"labels": []},
    "work": {"branch": "fix/{number}-{slug}", "worktrees": "", "rules": []},
    "docs": {"fixer": [], "verifier": [], "opener": [], "merger": [], "backport": []},
    "request": {"template": "", "labels": [], "milestone": "issue", "update": "rebase", "pre_push": [],
                "draft": False, "language": ""},
    "merge": {"ask": True, "method": "merge", "require_jobs": [], "play_jobs": [], "timeout": 14400},
    "backport": {"mode": "never", "milestone": "", "branch": "", "name": "backport/{branch}-{request}",
                 "auto_labels": []},
    "state_dir": "",
}
CHOICES = {
    ("forge", "kind"): {"", "gitlab", "github"},
    ("request", "milestone"): {"issue", "current", "none"},
    ("request", "update"): {"rebase", "merge"},
    ("merge", "method"): {"merge", "squash", "rebase"},
    ("backport", "mode"): {"never", "ask", "auto"},
}


@dataclass
class Config:
    host: str
    path: str
    file: Path
    data: dict = field(default_factory=dict)

    def __getitem__(self, section: str):
        return self.data[section]

    @property
    def kind(self) -> str:
        return self.data["forge"]["kind"] or ("github" if self.host == "github.com" else "gitlab")

    @property
    def state_dir(self) -> Path:
        raw = self.data["state_dir"] or str(STATE_ROOT / self.host / self.path)
        return Path(raw).expanduser()


def merge_defaults(raw: dict, where: Path) -> dict:
    data: dict = {}
    for key, default in DEFAULTS.items():
        if isinstance(default, dict):
            section = raw.get(key, {})
            if not isinstance(section, dict):
                raise SweepError(f"{where}: [{key}] must be a table")
            unknown = set(section) - set(default)
            if unknown:
                raise SweepError(f"{where}: unknown key(s) in [{key}]: {', '.join(sorted(unknown))}")
            merged = {**default, **section}
            for name, value in merged.items():
                if type(value) is not type(default[name]):
                    raise SweepError(f"{where}: {key}.{name} must be {type(default[name]).__name__}")
                allowed = CHOICES.get((key, name))
                if allowed and value not in allowed:
                    raise SweepError(f"{where}: {key}.{name} = {value!r}, expected one of {sorted(allowed - {''})}")
            data[key] = merged
        else:
            data[key] = raw.get(key, default)
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise SweepError(f"{where}: unknown section(s): {', '.join(sorted(unknown))}")
    return data


def load_config(run=run_cli, file: str | None = None) -> Config:
    code, out, _ = run(["git", "remote", "get-url", "origin"])
    if code != 0:
        raise SweepError("no origin remote: run from the repository's checkout")
    host, path = parse_remote(out)
    where = Path(file).expanduser() if file else config_path(host, path)
    if not where.is_file():
        raise SweepError(f"no config at {where}; write one as references/config.md describes")
    return Config(host, path, where, merge_defaults(tomllib.loads(where.read_text(encoding="utf-8")), where))


# ---------------------------------------------------------------- issues and requests

@dataclass
class Issue:
    number: int
    title: str
    state: str  # open | closed
    labels: list[str]
    assignees: list[str]
    author: str
    milestone: str
    url: str
    updated_at: str
    closed_by: str = ""
    closed_at: str = ""


@dataclass
class Request:
    number: int
    title: str
    body: str
    branch: str
    author: str


def wanted(issue: Issue, flt: dict, milestone: str) -> bool:
    """Whether an open issue still matches the filter, whoever holds it."""
    labels = set(issue.labels)
    return (issue.state == "open"
            and (not milestone or issue.milestone == milestone)
            and (not flt["labels_any"] or bool(labels & set(flt["labels_any"])))
            and set(flt["labels_all"]) <= labels
            and not labels & set(flt["exclude_labels"])
            and issue.author not in flt["exclude_authors"])


def backport_target(cfg: Config, issue: Issue, branches: list[str]) -> tuple[str, str]:
    """(target branch or "", why) from the issue's milestone and the [backport] patterns."""
    bp = cfg["backport"]
    if bp["mode"] == "never":
        return "", "backport.mode is never"
    if not bp["milestone"] or not bp["branch"]:
        return "", "backport.milestone and backport.branch are not both set"
    pattern = "^" + re.escape(bp["milestone"]).replace(r"\{n\}", r"(?P<n>[\w.-]+)") + "$"
    m = re.match(pattern, issue.milestone or "")
    if not m:
        return "", f"milestone {issue.milestone or '(none)'} does not match {bp['milestone']!r}"
    target = bp["branch"].replace("{n}", m.group("n"))
    if target not in branches:
        return "", f"{target} does not exist on the remote"
    return target, ""


def mentions(number: int, text: str | None) -> bool:
    return re.search(rf"(?<![\d!]){number}(?!\d)", text or "") is not None


def remote_branches(run) -> list[str]:
    code, out, err = run(["git", "ls-remote", "--heads", "origin"])
    if code != 0:
        raise SweepError(f"git ls-remote failed: {err.strip()}")
    return [line.split("refs/heads/", 1)[1] for line in out.splitlines() if "refs/heads/" in line]


def matching_branches(branches: list[str], pattern: str) -> list[str]:
    return [b for b in branches if fnmatch.fnmatch(b, pattern)]


class GitLab:
    name, sigil = "GitLab", "!"

    def __init__(self, cfg: Config, run=run_cli):
        self.run, self.cfg = run, cfg
        self.base = f"projects/{quote(str(cfg['forge']['project']), safe='') or ':id'}"

    def api(self, path: str, *extra: str):
        return call(self.run, ["glab", "api", path, *extra])

    def pages(self, path: str) -> list:
        return call(self.run, ["glab", "api", "--paginate", path]) or []

    def me(self) -> tuple[str, str]:
        who = self.cfg["forge"]["assignee"]
        if who == "me":
            user = self.api("user")
        else:
            found = self.api(f"users?username={quote(who)}")
            if not found:
                raise SweepError(f"no GitLab user {who}")
            user = found[0]
        return user["username"], str(user["id"])

    def current_milestone(self, today: date) -> str:
        found = self.pages(f"{self.base}/milestones?state=active&include_ancestors=true&per_page=100")
        live = [m["title"] for m in found
                if m.get("start_date") and m.get("due_date") and m["start_date"] <= today.isoformat() <= m["due_date"]]
        if len(live) != 1:
            raise SweepError(f"{len(live)} active milestones cover {today}: {', '.join(live) or 'none'}; name one in filter.milestone")
        return live[0]

    @staticmethod
    def issue_of(raw: dict) -> Issue:
        return Issue(raw["iid"], raw["title"], "open" if raw["state"] == "opened" else "closed", raw.get("labels", []),
                     [a["username"] for a in raw.get("assignees", [])], raw["author"]["username"],
                     (raw.get("milestone") or {}).get("title", ""), raw["web_url"], raw.get("updated_at", ""),
                     (raw.get("closed_by") or {}).get("username", ""), raw.get("closed_at") or "")

    def issues(self, milestone: str) -> list[Issue]:
        query = f"&milestone={quote(milestone)}" if milestone else ""
        return [self.issue_of(i) for i in self.pages(f"{self.base}/issues?state=opened&per_page=100{query}")]

    def issues_by_number(self, numbers: list[int]) -> list[Issue]:
        if not numbers:
            return []
        query = "&".join(f"iids[]={n}" for n in numbers)
        return [self.issue_of(i) for i in self.pages(f"{self.base}/issues?state=all&per_page=100&{query}")]

    def issue(self, number: int) -> Issue:
        return self.issue_of(self.api(f"{self.base}/issues/{number}"))

    def assign(self, number: int, user_ids: list[str]) -> None:
        self.api(f"{self.base}/issues/{number}", "-X", "PUT", "-F", f"assignee_ids=[{','.join(user_ids)}]")

    def assignee_ids(self, number: int, drop: str) -> list[str]:
        raw = self.api(f"{self.base}/issues/{number}")
        return [str(a["id"]) for a in raw["assignees"] if a["username"] != drop]

    def open_requests(self) -> list[Request]:
        return [Request(m["iid"], m["title"], m.get("description") or "", m["source_branch"], m["author"]["username"])
                for m in self.pages(f"{self.base}/merge_requests?state=opened&per_page=100")]

    # pipelines

    def request_state(self, number: int) -> dict:
        mr = self.api(f"{self.base}/merge_requests/{number}")
        pipe = mr.get("head_pipeline") or {}
        return {"state": {"opened": "open"}.get(mr["state"], mr["state"]), "head": mr["sha"],
                "pipeline": pipe.get("id"), "pipeline_sha": pipe.get("sha"), "pipeline_status": pipe.get("status"),
                "merge_status": mr.get("detailed_merge_status", ""), "target": mr["target_branch"]}

    def jobs(self, pipeline: int) -> dict[str, dict]:
        """Latest job per name: {name: {id, status, allow_failure}}."""
        latest: dict[str, dict] = {}
        for job in sorted(self.pages(f"{self.base}/pipelines/{pipeline}/jobs?per_page=100&include_retried=false"),
                          key=lambda j: j["id"]):
            latest[job["name"]] = {"id": job["id"], "status": job["status"], "allow_failure": job.get("allow_failure", False)}
        return latest

    def play(self, job_id: int) -> None:
        self.api(f"{self.base}/jobs/{job_id}/play", "-X", "POST")


class GitHub:
    name, sigil = "GitHub", "#"

    def __init__(self, cfg: Config, run=run_cli):
        self.run, self.cfg = run, cfg
        self.base = f"repos/{cfg.path}"

    def api(self, path: str, *extra: str):
        return call(self.run, ["gh", "api", path, *extra])

    def pages(self, path: str) -> list:
        return call(self.run, ["gh", "api", "--paginate", path]) or []

    def me(self) -> tuple[str, str]:
        who = self.cfg["forge"]["assignee"]
        login = self.api("user")["login"] if who == "me" else who
        return login, login

    def milestone_number(self, title: str) -> int:
        for m in self.pages(f"{self.base}/milestones?state=all&per_page=100"):
            if m["title"] == title:
                return m["number"]
        raise SweepError(f"no milestone titled {title!r}")

    def current_milestone(self, today: date) -> str:
        found = [m for m in self.pages(f"{self.base}/milestones?state=open&per_page=100")
                 if m.get("due_on") and m["due_on"][:10] >= today.isoformat()]
        if not found:
            raise SweepError(f"no open milestone is due on or after {today}; name one in filter.milestone")
        return min(found, key=lambda m: m["due_on"])["title"]

    @staticmethod
    def issue_of(raw: dict) -> Issue:
        return Issue(raw["number"], raw["title"], raw["state"], [label["name"] for label in raw.get("labels", [])],
                     [a["login"] for a in raw.get("assignees", [])], raw["user"]["login"],
                     (raw.get("milestone") or {}).get("title", ""), raw["html_url"], raw.get("updated_at", ""),
                     (raw.get("closed_by") or {}).get("login", ""), raw.get("closed_at") or "")

    def issues(self, milestone: str) -> list[Issue]:
        query = f"&milestone={self.milestone_number(milestone)}" if milestone else ""
        raw = self.pages(f"{self.base}/issues?state=open&per_page=100{query}")
        return [self.issue_of(i) for i in raw if "pull_request" not in i]

    def issues_by_number(self, numbers: list[int]) -> list[Issue]:
        return [self.issue(n) for n in numbers]

    def issue(self, number: int) -> Issue:
        return self.issue_of(self.api(f"{self.base}/issues/{number}"))

    def assign(self, number: int, user_ids: list[str]) -> None:
        current = self.issue(number).assignees
        drop = [a for a in current if a not in user_ids]
        add = [a for a in user_ids if a not in current]
        if drop:
            self.api(f"{self.base}/issues/{number}/assignees", "-X", "DELETE", *[x for a in drop for x in ("-f", f"assignees[]={a}")])
        if add:
            self.api(f"{self.base}/issues/{number}/assignees", "-X", "POST", *[x for a in add for x in ("-f", f"assignees[]={a}")])

    def assignee_ids(self, number: int, drop: str) -> list[str]:
        return [a for a in self.issue(number).assignees if a != drop]

    def open_requests(self) -> list[Request]:
        return [Request(p["number"], p["title"], p.get("body") or "", p["head"]["ref"], p["user"]["login"])
                for p in self.pages(f"{self.base}/pulls?state=open&per_page=100")]

    def request_state(self, number: int) -> dict:
        pr = call(self.run, ["gh", "pr", "view", str(number), "--json",
                             "state,headRefOid,baseRefName,mergeStateStatus,statusCheckRollup"])
        checks = pr.get("statusCheckRollup") or []
        failed = [c for c in checks if c.get("conclusion") in ("FAILURE", "CANCELLED", "TIMED_OUT")
                  or c.get("state") in ("FAILURE", "ERROR")]
        running = [c for c in checks if c.get("status") not in (None, "COMPLETED") or c.get("state") in ("PENDING", "EXPECTED")]
        status = "failed" if failed else "running" if running else "success" if checks else None
        return {"state": pr["state"].lower(), "head": pr["headRefOid"], "pipeline": "checks" if checks else None,
                "pipeline_sha": pr["headRefOid"], "pipeline_status": status,
                "merge_status": pr.get("mergeStateStatus", ""), "target": pr["baseRefName"]}

    def jobs(self, pipeline) -> dict[str, dict]:
        raise SweepError("GitHub has no manual jobs to play; trigger a workflow_dispatch workflow by hand instead")

    def checks(self, number: int) -> dict[str, dict]:
        pr = call(self.run, ["gh", "pr", "view", str(number), "--json", "statusCheckRollup"])
        out = {}
        for c in pr.get("statusCheckRollup") or []:
            name = c.get("name") or c.get("context", "?")
            out[name] = {"id": c.get("detailsUrl") or c.get("targetUrl") or "",
                         "status": (c.get("conclusion") or c.get("status") or c.get("state") or "?").lower(),
                         "allow_failure": False}
        return out

    def play(self, job_id) -> None:
        raise SweepError("GitHub has no manual jobs to play")


def forge(cfg: Config, run=run_cli):
    return (GitHub if cfg.kind == "github" else GitLab)(cfg, run)
