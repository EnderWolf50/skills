# /// script
# requires-python = ">=3.11"
# ///
"""Pipeline helpers between opening a request and merging it with the merge-pr skill.

uv run ship.py jobs <number>                     print the head pipeline and its latest job per name
uv run ship.py need <number>                     the require jobs for this request, as `--require-job <name>` arguments
uv run ship.py play <number> [--timeout S]       play the request's play jobs as each turns manual; wait until they all pass
uv run ship.py watch <number>... [--file F]      one line per state change until every request is merged or closed
uv run ship.py backport <issue>                  the release branch backport.* picks for an issue, and whether its labels
                                                 authorize the backport without asking

A request's jobs are merge.play_jobs and merge.require_jobs plus those of every merge.when entry whose paths match a file
the request changes (a renamed file counts under both names).
play is GitLab only: it plays a listed job that sits at manual, fails on a listed job that fails or on any failed job
that may not fail, and passes once every listed job the pipeline has is green on the request's head.
Exit codes: 0 done, 1 error, 2 blocked (failed, closed, head moved), 3 timed out.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from sweep import Config, SweepError, backport_target, forge, load_config, remote_branches, run_cli, select_jobs

OK, ERROR, BLOCKED, TIMED_OUT = 0, 1, 2, 3
FAILED = {"failed", "canceled", "canceling"}
RUNNING = {"created", "waiting_for_resource", "preparing", "pending", "running", "scheduled"}


def cmd_jobs(cfg: Config, run, number: int) -> int:
    f = forge(cfg, run)
    st = f.request_state(number)
    print(f"{f.sigil}{number} {st['state']} head {st['head'][:10]} -> {st['target']}, merge status {st['merge_status']}")
    if st["pipeline"] is None:
        print("no pipeline for this head")
        return OK
    print(f"pipeline {st['pipeline']} {st['pipeline_status']} on {str(st['pipeline_sha'])[:10]}")
    jobs = f.checks(number) if cfg.kind == "github" else f.jobs(st["pipeline"])
    for name, job in jobs.items():
        print(f"  {job['id']} {name} {job['status']}{' (may fail)' if job['allow_failure'] else ''}")
    return OK


def play_verdict(jobs: dict[str, dict], play: list[str], pipeline_status: str) -> tuple[str, str, list[int]]:
    """(ok|wait|blocked, reason, job ids to play now) for one read of the pipeline."""
    to_play = [jobs[n]["id"] for n in play if n in jobs and jobs[n]["status"] == "manual"]
    failed = [n for n, j in jobs.items() if j["status"] in FAILED and (n in play or not j["allow_failure"])]
    if failed:
        return "blocked", f"failed: {', '.join(failed)}", []
    present = [n for n in play if n in jobs]
    busy = [n for n, j in jobs.items() if j["status"] in RUNNING]
    skipped = [n for n in present if jobs[n]["status"] == "skipped"]
    if skipped and not busy and not to_play:
        return "blocked", f"skipped with nothing left running: {', '.join(skipped)}", []
    if to_play or busy or any(jobs[n]["status"] != "success" for n in present) or pipeline_status in RUNNING:
        waiting = [f"{n} {jobs[n]['status']}" for n in present if jobs[n]["status"] != "success"]
        return "wait", ", ".join(waiting) or f"pipeline {pipeline_status}", to_play
    return "ok", f"passed: {', '.join(present) or 'no listed job in this pipeline'}", []


def jobs_for(cfg: Config, f, number: int) -> tuple[list[str], list[str]]:
    """(play_jobs, require_jobs) of one request; the changed paths are read only when a merge.when entry needs them."""
    merge = cfg["merge"]
    return select_jobs(merge, f.changed_files(number) if merge["when"] else [])


def cmd_need(cfg: Config, run, number: int) -> int:
    _, require = jobs_for(cfg, forge(cfg, run), number)
    print(" ".join(f"--require-job {name}" for name in require))
    return OK


def cmd_play(cfg: Config, run, number: int, timeout: int, interval: int, sleep=time.sleep, clock=time.monotonic) -> int:
    if cfg.kind != "gitlab":
        print("error: play is GitLab only; GitHub has no manual jobs")
        return ERROR
    f = forge(cfg, run)
    play, _ = jobs_for(cfg, f, number)
    deadline, last, head = clock() + timeout, None, None
    while True:
        st = f.request_state(number)
        if st["state"] != "open":
            print(f"!{number} is {st['state']}")
            return OK if st["state"] == "merged" else BLOCKED
        head = head or st["head"]
        if st["head"] != head:
            print(f"head moved: {head[:10]} -> {st['head'][:10]}")
            return BLOCKED
        if st["pipeline"] is None or st["pipeline_sha"] != st["head"]:
            kind, reason, ids = "wait", "no pipeline for the head yet", []
        else:
            kind, reason, ids = play_verdict(f.jobs(st["pipeline"]), play, st["pipeline_status"])
        for job_id in ids:
            f.play(job_id)
            print(f"played job {job_id}", flush=True)
        line = f"{time.strftime('%H:%M')} pipeline {st['pipeline']} {st['pipeline_status']}: {kind}, {reason}"
        if line.split(" ", 1)[1] != (last or " ").split(" ", 1)[1]:
            print(line, flush=True)
            last = line
        if kind == "ok":
            print(f"head {head} ready for merge-pr")
            return OK
        if kind == "blocked":
            return BLOCKED
        if clock() >= deadline:
            print(f"timed out after {timeout}s: {reason}")
            return TIMED_OUT
        sleep(interval)


def read_numbers(numbers: list[int], file: str | None) -> list[int]:
    extra = []
    if file and Path(file).is_file():
        extra = [int(t.lstrip("!#")) for t in Path(file).read_text(encoding="utf-8").split() if t.lstrip("!#").isdigit()]
    return list(dict.fromkeys([*numbers, *extra]))


def cmd_watch(cfg: Config, run, numbers: list[int], file: str | None, interval: int, sleep=time.sleep) -> int:
    f = forge(cfg, run)
    seen: dict[int, str] = {}
    while True:
        watched = read_numbers(numbers, file)
        if not watched:
            print("error: nothing to watch")
            return ERROR
        for n in watched:
            try:
                st = f.request_state(n)
            except SweepError as e:
                state = f"unreadable: {e}"
            else:
                state = (f"{st['state']} {st['merge_status']} pipeline {st['pipeline']} {st['pipeline_status']} "
                         f"head {st['head'][:10]}")
            if seen.get(n) != state:
                print(f"{f.sigil}{n}: {state}", flush=True)
                seen[n] = state
        if all(seen.get(n, "").split(" ")[0] in ("merged", "closed") for n in watched):
            print("every watched request is merged or closed")
            return OK
        sleep(interval)


def cmd_backport(cfg: Config, run, number: int) -> int:
    issue = forge(cfg, run).issue(number)
    target, why = backport_target(cfg, issue, remote_branches(run))
    if not target:
        print(f"#{number}: no backport ({why})")
        return OK
    bp = cfg["backport"]
    by_label = sorted(set(issue.labels) & set(bp["auto_labels"]))
    if bp["mode"] == "auto" or by_label:
        reason = f"label {', '.join(by_label)}" if by_label else "backport.mode is auto"
        print(f"#{number}: backport to {target}, authorized by {reason}")
    else:
        print(f"#{number}: candidate for {target}; ask the user before opening it")
    for doc in cfg["docs"]["backport"]:
        print(f"read before opening it: {doc}")
    return OK


def main(argv: list[str], run=run_cli, sleep=time.sleep, clock=time.monotonic) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--config", help="config file; default: from the checkout's origin remote")
    sub = p.add_subparsers(dest="cmd", required=True)
    num = lambda s: int(s.lstrip("!#"))  # noqa: E731
    sub.add_parser("jobs").add_argument("number", type=num)
    pl = sub.add_parser("play")
    pl.add_argument("number", type=num)
    pl.add_argument("--timeout", type=int, help="seconds; default merge.timeout")
    pl.add_argument("--interval", type=int, default=60)
    w = sub.add_parser("watch")
    w.add_argument("numbers", type=num, nargs="*")
    w.add_argument("--file", help="file of request numbers, re-read every round so numbers can be added")
    w.add_argument("--interval", type=int, default=60)
    sub.add_parser("need").add_argument("number", type=num)
    sub.add_parser("backport").add_argument("number", type=num)
    args = p.parse_args(argv)
    try:
        cfg = load_config(run, args.config)
        if args.cmd == "jobs":
            return cmd_jobs(cfg, run, args.number)
        if args.cmd == "play":
            return cmd_play(cfg, run, args.number, args.timeout or cfg["merge"]["timeout"], args.interval, sleep, clock)
        if args.cmd == "need":
            return cmd_need(cfg, run, args.number)
        if args.cmd == "watch":
            return cmd_watch(cfg, run, args.numbers, args.file, args.interval, sleep)
        return cmd_backport(cfg, run, args.number)
    except SweepError as e:
        print(f"error: {e}")
        return ERROR


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
