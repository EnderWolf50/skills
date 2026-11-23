# /// script
# requires-python = ">=3.10"
# ///
"""Merge a GitHub pull request or a GitLab merge request once its pipeline is green, pinned to one head commit.

uv run merge_pr.py <number> [--sha SHA] [--target BRANCH] [--require-job NAME]... [--method merge|squash|rebase]
                   [--allow-no-pipeline] [--timeout 60] [--interval 5] [--dry-run] [--repo R] [--forge github|gitlab]

Exit codes: 0 merged (or ready, with --dry-run), 1 error, 2 blocked, 3 timed out, 4 merge refused.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import quote

MERGED, ERROR, BLOCKED, TIMED_OUT, REFUSED = 0, 1, 2, 3, 4
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
HTTP_STATUS = re.compile(r"HTTP (\d{3})")


@dataclass
class Verdict:
    kind: str  # "ready", "wait" or "blocked"
    reason: str = ""


READY = Verdict("ready")


def wait(reason: str) -> Verdict:
    return Verdict("wait", reason)


def blocked(reason: str) -> Verdict:
    return Verdict("blocked", reason)


@dataclass
class State:
    head: str
    target: str
    summary: str
    merge: Verdict
    pipeline: Verdict
    jobs: dict[str, str] = field(default_factory=dict)  # required job -> success|running|manual|failed|skipped|missing


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def run_cli(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


def call(run, cmd: list[str]):
    """Run a glab/gh command and parse its JSON; a failure raises ApiError with the server's message and HTTP status."""
    code, out, err = run(cmd)
    if code == 0:
        return json.loads(out) if out.strip() else None
    try:
        body = json.loads(out)
        message = body.get("message") or body.get("error") or out.strip() if isinstance(body, dict) else out.strip()
    except json.JSONDecodeError:
        message = (out + err).strip()
    status = HTTP_STATUS.search(err)
    raise ApiError(f"{' '.join(cmd[:3])}: {message}", int(status.group(1)) if status else None)


JOB_REASONS = {
    "running": "required job {name} is still running",
    "manual": "required job {name} was never played (manual job)",
    "failed": "required job {name} failed",
    "skipped": "required job {name} was skipped",
    "missing": "no job named {name} in the pipeline",
}


def judge(state: State, pinned: str, target: str | None) -> Verdict:
    if state.head != pinned:
        return blocked(f"head moved: {pinned[:10]} -> {state.head[:10]}")
    if target and state.target != target:
        return blocked(f"targets {state.target}, expected {target}")
    jobs = []
    for name, status in state.jobs.items():
        if status == "missing" and state.pipeline.kind == "wait":  # jobs and checks can register after the pipeline starts
            jobs.append(wait(f"required job {name} has not appeared yet"))
        elif status == "success":
            jobs.append(READY)
        else:
            jobs.append(Verdict("wait" if status == "running" else "blocked", JOB_REASONS[status].format(name=name)))
    checks = [state.pipeline, *jobs, state.merge]
    for v in checks:
        if v.kind == "blocked":
            return v
    waiting = [v.reason for v in checks if v.kind == "wait"]
    return wait("; ".join(waiting)) if waiting else READY


# ---------------------------------------------------------------- GitLab

GITLAB_WAIT = {"checking", "unchecked", "preparing", "approvals_syncing", "ci_must_pass", "ci_still_running",
               "status_checks_must_pass", "security_policy_pipeline_check"}
GITLAB_BLOCK = {
    "conflict": "conflicts with the target branch",
    "need_rebase": "needs a rebase onto the target branch",
    "not_approved": "approval required",
    "draft_status": "is a draft",
    "discussions_not_resolved": "has unresolved discussions",
    "requested_changes": "a reviewer requested changes",
    "merge_request_blocked": "blocked by another merge request",
    "merge_time": "may not merge before its scheduled time",
    "commits_status": "source branch is missing or has no commits",
    "jira_association_missing": "title or description must reference a Jira issue",
    "security_policy_violations": "security policies are not satisfied",
    "locked_paths": "touches paths locked by other users",
    "locked_lfs_files": "touches LFS files locked by other users",
    "title_regex": "title does not match the project's required pattern",
}
GITLAB_PIPELINE_WAIT = {"created", "waiting_for_resource", "preparing", "pending", "running", "scheduled"}
GITLAB_JOB = {"success": "success", "manual": "manual", "failed": "failed", "canceled": "failed",
              "canceling": "failed", "skipped": "skipped"}


def gitlab_merge_verdict(mr: dict) -> Verdict:
    if mr["state"] != "opened":
        return blocked(f"merge request is {mr['state']}")
    status = mr.get("detailed_merge_status")
    if status == "mergeable":
        return READY
    if status in GITLAB_WAIT:
        return wait(f"merge status {status}")
    return blocked(GITLAB_BLOCK.get(status, f"merge status {status}"))


def gitlab_pipeline_verdict(pipe: dict) -> Verdict:
    status, pid = pipe["status"], pipe["id"]
    if status == "success":
        return READY
    if status in GITLAB_PIPELINE_WAIT:
        return wait(f"pipeline {pid} {status}")
    if status == "manual":
        return blocked(f"pipeline {pid} stops at a manual job that blocks it")
    return blocked(f"pipeline {pid} {status}")


class GitLab:
    name = "GitLab"

    def __init__(self, run, repo: str | None):
        self.run, self.repo_args, self._has_ci = run, (["-R", repo] if repo else []), None

    def api(self, path: str, *extra: str):
        return call(self.run, ["glab", "api", path, *self.repo_args, *extra])

    def api_list(self, path: str) -> list:
        code, out, err = self.run(["glab", "api", path, *self.repo_args, "--paginate", "--output", "ndjson"])
        if code != 0:
            call(lambda _: (code, out, err), ["glab", "api", path])
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def check_method(self, method: str) -> None:
        if method == "rebase":
            raise ApiError("GitLab takes the merge method from the project; use merge or squash")

    def has_ci(self, sha: str) -> bool:
        if self._has_ci is None:
            path = self.api("projects/:id").get("ci_config_path") or ".gitlab-ci.yml"
            if "@" in path or "://" in path:  # a config in another project or at a URL
                self._has_ci = True
            else:
                try:
                    self.api(f"projects/:id/repository/files/{quote(path, safe='')}?ref={sha}")
                    self._has_ci = True
                except ApiError as e:
                    if e.status != 404:
                        raise
                    self._has_ci = False
        return self._has_ci

    def read(self, number: str, required_jobs: list[str], allow_no_pipeline: bool) -> State:
        mr = self.api(f"projects/:id/merge_requests/{number}")
        head, pipe = mr["sha"], mr.get("head_pipeline")
        jobs: dict[str, str] = {}
        if pipe is None:
            if allow_no_pipeline:
                pipeline = READY
            elif self.has_ci(head):
                pipeline = wait("no pipeline for this head yet (not created, or you cannot view pipelines)")
            else:
                pipeline = READY
            jobs = {name: "missing" for name in required_jobs}
            pipe_text = "none"
        else:
            pipe_text = f"{pipe['id']} {pipe['status']}"
            if pipe.get("sha") and pipe["sha"] != head:
                pipeline = wait(f"pipeline {pipe['id']} is for an older commit")
            else:
                pipeline = gitlab_pipeline_verdict(pipe)
            if required_jobs:
                found = {j["name"]: GITLAB_JOB.get(j["status"], "running")
                         for j in self.api_list(f"projects/:id/pipelines/{pipe['id']}/jobs?per_page=100")}
                jobs = {name: found.get(name, "missing") for name in required_jobs}
        summary = f"merge_status={mr.get('detailed_merge_status')} pipeline={pipe_text}"
        return State(head, mr["target_branch"], summary, gitlab_merge_verdict(mr), pipeline, jobs)

    def merge(self, number: str, sha: str, method: str) -> str:
        extra = ["-X", "PUT", "-f", f"sha={sha}"] + (["-f", "squash=true"] if method == "squash" else [])
        res = self.api(f"projects/:id/merge_requests/{number}/merge", *extra)
        if res.get("state") != "merged":
            raise ApiError(f"merge answered with state {res.get('state')}")
        return res.get("merge_commit_sha") or res.get("squash_commit_sha") or res.get("sha") or ""

    def report_issues(self, number: str, target: str) -> None:
        default = self.api("projects/:id")["default_branch"]
        issues = self.api_list(f"projects/:id/merge_requests/{number}/closes_issues")
        report(target, default, [(f"#{i.get('iid', i.get('id'))}", i.get("state", "?")) for i in issues])


# ---------------------------------------------------------------- GitHub

CHECK_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
STATUS_WAIT = {"PENDING", "EXPECTED"}


def github_check(item: dict) -> tuple[str, str]:
    """One statusCheckRollup entry as (name, success|running|failed)."""
    if item.get("__typename") == "StatusContext":
        state = item.get("state")
        return item.get("context", "?"), "success" if state == "SUCCESS" else "running" if state in STATUS_WAIT else "failed"
    if item.get("status") != "COMPLETED":
        return item.get("name", "?"), "running"
    return item.get("name", "?"), "success" if item.get("conclusion") in CHECK_OK else "failed"


def github_merge_verdict(pr: dict) -> Verdict:
    if pr["state"] != "OPEN":
        return blocked(f"pull request is {pr['state'].lower()}")
    if pr.get("isDraft"):
        return blocked("is a draft")
    if pr.get("mergeable") == "CONFLICTING":
        return blocked("conflicts with the base branch")
    status = pr.get("mergeStateStatus")
    if status in ("CLEAN", "HAS_HOOKS", "UNSTABLE"):  # UNSTABLE: a failing check, which the pipeline verdict reports
        return READY
    if status == "DIRTY":
        return blocked("conflicts with the base branch")
    if status == "BEHIND":
        return blocked("head is behind the base branch, which must be up to date")
    if status == "BLOCKED":
        review = pr.get("reviewDecision")
        if review == "REVIEW_REQUIRED":
            return blocked("a review is required")
        if review == "CHANGES_REQUESTED":
            return blocked("a reviewer requested changes")
        return wait("branch protection blocks the merge (a required check or rule)")
    return wait(f"merge state {status}")


class GitHub:
    name = "GitHub"
    FIELDS = "number,state,isDraft,headRefOid,baseRefName,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup"

    def __init__(self, run, repo: str | None):
        self.run, self.repo, self._has_ci = run, repo, None
        self.slug = repo or "{owner}/{repo}"

    def gh(self, *args: str):
        return call(self.run, ["gh", *args, *(["-R", self.repo] if self.repo else [])])

    def api(self, path: str, *extra: str):
        return call(self.run, ["gh", "api", path, *extra])

    def check_method(self, method: str) -> None:
        pass

    def has_ci(self, sha: str) -> bool:
        if self._has_ci is None:
            try:
                self.api(f"repos/{self.slug}/contents/.github/workflows?ref={sha}")
                self._has_ci = True
            except ApiError as e:
                if e.status != 404:
                    raise
                self._has_ci = False
        return self._has_ci

    def read(self, number: str, required_jobs: list[str], allow_no_pipeline: bool) -> State:
        pr = self.gh("pr", "view", number, "--json", self.FIELDS)
        head, rollup = pr["headRefOid"], pr.get("statusCheckRollup") or []
        checks = [github_check(item) for item in rollup]
        if not checks:
            if allow_no_pipeline or not self.has_ci(head):
                pipeline = READY
            else:
                pipeline = wait("no checks reported for this head yet")
        elif failed := [n for n, s in checks if s == "failed"]:
            pipeline = blocked(f"checks failed: {', '.join(failed)}")
        elif running := [n for n, s in checks if s == "running"]:
            pipeline = wait(f"checks running: {', '.join(running)}")
        else:
            pipeline = READY
        found = dict(checks)
        jobs = {name: found.get(name, "missing") for name in required_jobs}
        passed = sum(1 for _, s in checks if s == "success")
        summary = f"merge_state={pr.get('mergeStateStatus')} checks={passed}/{len(checks)} passed"
        return State(head, pr["baseRefName"], summary, github_merge_verdict(pr), pipeline, jobs)

    def merge(self, number: str, sha: str, method: str) -> str:
        res = self.api(f"repos/{self.slug}/pulls/{number}/merge", "-X", "PUT",
                       "-f", f"sha={sha}", "-f", f"merge_method={method}")
        if not res.get("merged"):
            raise ApiError(f"merge answered: {res.get('message')}")
        return res.get("sha", "")

    def report_issues(self, number: str, target: str) -> None:
        default = self.api(f"repos/{self.slug}")["default_branch"]
        refs = self.gh("pr", "view", number, "--json", "closingIssuesReferences")["closingIssuesReferences"]
        rows = []
        for ref in refs:
            repo = f"{ref['repository']['owner']['login']}/{ref['repository']['name']}"
            rows.append((f"{repo}#{ref['number']}", self.api(f"repos/{repo}/issues/{ref['number']}")["state"]))
        report(target, default, rows)


# ---------------------------------------------------------------- main

def report(target: str, default: str, issues: list[tuple[str, str]]) -> None:
    if target != default:
        print(f"target {target} is not the default branch ({default}): closing keywords do not close issues")
    for ref, state in issues:
        print(f"issue {ref}: {state}")


def detect_forge(run, repo: str | None) -> str:
    if repo and "github.com" in repo:
        return "github"
    code, out, _ = run(["git", "remote", "get-url", "origin"])
    if code != 0:
        raise ApiError("no git remote here: run from the repository or pass --forge")
    return "github" if "github.com" in out else "gitlab"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("number", help="pull request or merge request number (iid)")
    p.add_argument("--sha", help="full 40-character head SHA to pin; default: the head seen on the first read")
    p.add_argument("--target", help="expected target branch; any other target blocks")
    p.add_argument("--require-job", action="append", default=[], metavar="NAME",
                   help="job or check that must have run and passed (repeatable)")
    p.add_argument("--method", choices=["merge", "squash", "rebase"], default="merge")
    p.add_argument("--allow-no-pipeline", action="store_true", help="merge a head that has no pipeline or checks")
    p.add_argument("--timeout", type=int, default=60, help="seconds to keep waiting on a pending state (default 60)")
    p.add_argument("--interval", type=int, default=5, help="seconds between reads (default 5)")
    p.add_argument("--dry-run", action="store_true", help="report readiness without merging")
    p.add_argument("--repo", help="owner/repo (GitHub) or group/project (GitLab); default: the current checkout")
    p.add_argument("--forge", choices=["github", "gitlab"], help="default: from the origin remote")
    args = p.parse_args(argv)
    if args.sha and not FULL_SHA.match(args.sha):
        p.error("--sha must be the full 40-character lowercase SHA")
    return args


def main(argv: list[str], run=run_cli, sleep=time.sleep, clock=time.monotonic) -> int:
    args = parse_args(argv)
    try:
        forge = (GitHub if (args.forge or detect_forge(run, args.repo)) == "github" else GitLab)(run, args.repo)
        forge.check_method(args.method)
    except ApiError as e:
        print(f"error: {e}")
        return ERROR
    deadline, pinned, last, refused = clock() + args.timeout, args.sha, None, None
    while True:
        try:
            state = forge.read(args.number, args.require_job, args.allow_no_pipeline)
        except ApiError as e:
            print(f"error: {e}")
            return ERROR
        if pinned is None:
            pinned = state.head
            print(f"pinned to head {pinned}")
        verdict = judge(state, pinned, args.target)
        line = f"{state.head[:10]} {state.summary} -> {verdict.kind}" + (f": {verdict.reason}" if verdict.reason else "")
        if line != last:
            print(line)
            last = line
        if verdict.kind == "blocked":
            return BLOCKED
        if verdict.kind == "ready":
            if args.dry_run:
                print("ready to merge (dry run, nothing merged)")
                return MERGED
            try:
                commit = forge.merge(args.number, pinned, args.method)
            except ApiError as e:
                if e.status == 409:
                    print(f"blocked: {forge.name} refused the merge, the head no longer matches {pinned[:10]}")
                    return BLOCKED
                refused = str(e)
                print(f"merge refused: {e}")
            else:
                print(f"merged {pinned[:10]} into {state.target} as {commit[:10]}")
                try:
                    forge.report_issues(args.number, state.target)
                except ApiError as e:
                    print(f"could not read the closing issues: {e}")
                return MERGED
        if clock() >= deadline:
            if refused:
                print(f"gave up after {args.timeout}s; last refusal: {refused}")
                return REFUSED
            print(f"timed out after {args.timeout}s, still waiting: {verdict.reason}")
            return TIMED_OUT
        sleep(args.interval)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
