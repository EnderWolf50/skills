# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""Checks for ship.py with git and glab mocked: playing manual jobs, when play passes or blocks, watch, backport.

uv run test_ship.py
"""
import sys

import pytest

import ship
from conftest import Clock, Fake, ok

SHA, NEW = "a" * 40, "b" * 40
CFG = '[merge]\nplay_jobs = ["build", "e2e"]\n'


def mr(sha=SHA, state="opened", pipe_status="running", pipe_sha=SHA):
    return ok({"sha": sha, "state": state, "detailed_merge_status": "ci_still_running", "target_branch": "main",
               "head_pipeline": {"id": 9, "sha": pipe_sha, "status": pipe_status}})


def job(i, name, status, allow_failure=False):
    return {"id": i, "name": name, "status": status, "allow_failure": allow_failure}


def routes(mr_answers, job_answers, **over):
    r = {"git remote get-url": (0, "git@git.example.com:group/project.git\n", ""),
         "/play -X POST": ok({}),
         "pipelines/9/jobs": job_answers,
         "merge_requests/5": mr_answers}
    r.update(over)
    return r


def run(argv, r, config, text=CFG):
    fake, clock = Fake(r), Clock()
    return ship.main(["--config", config(text), *argv], run=fake, sleep=clock.sleep, clock=clock), fake


def test_play_plays_manual_jobs_as_they_appear_and_passes(capsys, config):
    jobs = [ok([job(1, "build", "manual"), job(2, "e2e", "created"), job(3, "unit", "success")]),
            ok([job(1, "build", "success"), job(4, "e2e", "manual"), job(3, "unit", "success")]),
            ok([job(1, "build", "success"), job(4, "e2e", "success"), job(3, "unit", "success")])]
    code, fake = run(["play", "5"], routes([mr(), mr(), mr(pipe_status="success")], jobs), config)
    assert code == ship.OK
    assert [c for c in fake.calls if "/play" in c] == ["glab api projects/:id/jobs/1/play -X POST",
                                                      "glab api projects/:id/jobs/4/play -X POST"]
    assert f"head {SHA} ready for merge-pr" in capsys.readouterr().out


def test_latest_job_per_name_wins(config):
    jobs = ok([job(1, "build", "failed"), job(8, "build", "success"), job(2, "e2e", "success")])
    code, _ = run(["play", "5"], routes(mr(pipe_status="success"), jobs), config)
    assert code == ship.OK


def test_a_failed_listed_job_blocks_even_if_it_may_fail(capsys, config):
    jobs = ok([job(1, "build", "success"), job(2, "e2e", "failed", allow_failure=True)])
    code, _ = run(["play", "5"], routes(mr(), jobs), config)
    assert code == ship.BLOCKED
    assert "failed: e2e" in capsys.readouterr().out


def test_an_unlisted_job_that_may_fail_does_not_block(config):
    jobs = ok([job(1, "build", "success"), job(2, "e2e", "success"), job(3, "lint", "failed", allow_failure=True)])
    code, _ = run(["play", "5"], routes(mr(pipe_status="success"), jobs), config)
    assert code == ship.OK


def test_a_skipped_listed_job_with_nothing_running_blocks(config):
    jobs = ok([job(1, "build", "success"), job(2, "e2e", "skipped")])
    code, _ = run(["play", "5"], routes(mr(pipe_status="success"), jobs), config)
    assert code == ship.BLOCKED


def test_a_moved_head_blocks(config):
    jobs = ok([job(1, "build", "running")])
    code, _ = run(["play", "5"], routes([mr(), mr(sha=NEW, pipe_sha=NEW)], jobs), config)
    assert code == ship.BLOCKED


def test_waits_for_the_head_pipeline_then_times_out(capsys, config):
    code, fake = run(["play", "5", "--timeout", "120"], routes(mr(pipe_sha=NEW), ok([])), config)
    assert code == ship.TIMED_OUT
    assert not any("pipelines/9/jobs" in c for c in fake.calls)
    assert "no pipeline for the head yet" in capsys.readouterr().out


def test_an_already_merged_request_is_done(config):
    code, _ = run(["play", "5"], routes(mr(state="merged"), ok([])), config)
    assert code == ship.OK


def test_play_refuses_github(capsys, config):
    r = {"git remote get-url": (0, "https://github.com/owner/repo.git\n", "")}
    code, _ = run(["play", "5"], r, config)
    assert code == ship.ERROR


def test_watch_prints_changes_until_every_request_is_done(capsys, config):
    r = routes([mr(), mr(), mr(state="merged")], ok([]), **{"merge_requests/6": mr(state="closed")})
    code, _ = run(["watch", "5", "6"], r, config)
    assert code == ship.OK
    out = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in out] == ["!5", "!6", "!5", "every watched request is merged or closed"]


BACKPORT = ('[backport]\nmode = "ask"\nmilestone = "Cycle {n}"\nbranch = "release/{n}"\n'
            'auto_labels = ["found-in-staging"]\n[docs]\nbackport = ["docs/backports.md"]\n')


def issue(labels):
    return ok({"iid": 5, "title": "t", "state": "opened", "labels": labels, "assignees": [], "author": {"username": "a"},
               "milestone": {"title": "Cycle 12"}, "web_url": "u", "updated_at": ""})


@pytest.mark.parametrize("labels, expected", [
    (["bug"], "candidate for release/12; ask the user"),
    (["bug", "found-in-staging"], "backport to release/12, authorized by label found-in-staging"),
])
def test_backport(capsys, config, labels, expected):
    r = {"git remote get-url": (0, "git@git.example.com:group/project.git\n", ""),
         "git ls-remote": (0, "x\trefs/heads/main\nx\trefs/heads/release/12\n", ""),
         "issues/5": issue(labels)}
    code, _ = run(["backport", "5"], r, config, BACKPORT)
    assert code == ship.OK
    out = capsys.readouterr().out
    assert expected in out
    assert "read before opening it: docs/backports.md" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
