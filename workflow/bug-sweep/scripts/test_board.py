# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""Checks for board.py with git, glab and gh mocked: statuses, ranking, triage notes, claim and release.

uv run test_board.py
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

import board
from conftest import Fake, ok

TODAY = date(2030, 5, 15)
CFG = '[filter]\nmilestone = "current"\nlabels_any = ["bug"]\n[rank]\nlabels = ["security", "bug"]\n'


def gl_issue(iid, labels=("bug",), assignees=(), state="opened", milestone="Cycle 12", author="ann", updated="2030-05-01T00:00:00Z"):
    return {"iid": iid, "title": f"issue {iid}", "state": state, "labels": list(labels),
            "assignees": [{"username": a, "id": 100 + i} for i, a in enumerate(assignees)],
            "author": {"username": author}, "milestone": {"title": milestone}, "web_url": f"https://git.example.com/i/{iid}",
            "updated_at": updated, "closed_by": {"username": "bob"} if state == "closed" else None,
            "closed_at": "2030-05-10T00:00:00Z" if state == "closed" else None}


def gitlab(issues, mrs=(), heads="", extra=None, **over):
    routes = {
        "git remote get-url": (0, "git@git.example.com:group/project.git\n", ""),
        "git ls-remote": (0, heads, ""),
        "=glab api user": ok({"username": "me", "id": 7}),
        "milestones?state=active": ok([{"title": "Cycle 11", "start_date": "2030-04-01", "due_date": "2030-04-30"},
                                       {"title": "Cycle 12", "start_date": "2030-05-01", "due_date": "2030-05-31"}]),
        "issues?state=opened": ok(issues),
        "issues?state=all": ok(extra or []),
        "merge_requests?state=opened": ok(list(mrs)),
    }
    routes.update(over)
    return routes


def run(argv, routes, cfg_text=CFG, config=None):
    fake = Fake(routes)
    code = board.main(["--config", config(cfg_text), *argv], run=fake, today=TODAY, sleep=lambda s: None)
    return code, fake


def board_text(tmp_path):
    return (tmp_path / "state" / "BOARD.md").read_text(encoding="utf-8")


def test_list_ranks_by_priority_label_then_age(capsys, config, tmp_path):
    issues = [gl_issue(30), gl_issue(20, labels=("bug", "security")), gl_issue(10), gl_issue(40, labels=("feature",))]
    code, fake = run([], gitlab(issues), config=config)
    assert code == board.OK
    out = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in out if line.strip()[:1].isdigit()] == ["#20", "#10", "#30"]
    assert "milestone=Cycle%2012" in " ".join(fake.calls)
    assert "#40" not in board_text(tmp_path)


def test_statuses_cover_mine_held_request_and_branch(capsys, config, tmp_path):
    issues = [gl_issue(1, assignees=["me"]), gl_issue(2, assignees=["kim"]), gl_issue(3), gl_issue(4), gl_issue(5)]
    mrs = [{"iid": 50, "title": "Fix issue 3", "description": "", "source_branch": "x", "author": {"username": "lee"}}]
    code, _ = run([], gitlab(issues, mrs, heads="abc\trefs/heads/fix/4-thing\n"), config=config)
    text = board_text(tmp_path)
    assert "mine, no request or branch" in text
    assert "held by kim" in text
    assert "unassigned but request !50 is open (lee)" in text
    assert "unassigned but branch fix/4-thing exists" in text
    out = capsys.readouterr().out
    assert "#5" in out and "#3 " not in out
    assert "mine: #1" in out


def test_triage_rank_and_groups_override_labels(capsys, config, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "triage.json").write_text(json.dumps({"generated_at": "2030-05-05T00:00:00+00:00", "issues": {
        "30": {"rank": 1, "tier": "A", "groups": ["grid"]},
        "20": {"rank": 2, "groups": ["grid"]},
        "99": {"rank": 3}}}), encoding="utf-8")
    issues = [gl_issue(20, assignees=["kim"]), gl_issue(30, updated="2030-05-06T00:00:00Z"), gl_issue(10)]
    code, fake = run([], gitlab(issues, extra=[gl_issue(99, state="closed")]), config=config)
    out = capsys.readouterr().out
    assert out.index("#30") < out.index("#10")
    assert "same group in progress: kim on #20 (grid)" in out
    assert "#10  bug  issue 10  [not triaged]" in out
    text = board_text(tmp_path)
    assert "updated after triage" in text
    assert "closed by bob on 2030-05-10" in text
    assert any("iids[]=99" in c for c in fake.calls)


def test_claim_assigns_and_reads_back(capsys, config):
    routes = gitlab([gl_issue(10)], **{"issues/10 -X PUT": ok({}), "=glab api projects/:id/issues/10": ok(gl_issue(10, assignees=["me"]))})
    code, fake = run(["claim", "10"], routes, config=config)
    assert code == board.OK
    assert fake.writes() == ["glab api projects/:id/issues/10 -X PUT -F assignee_ids=[7]"]
    assert "#10 assigned to me" in capsys.readouterr().out


def test_claim_refuses_an_issue_someone_holds(capsys, config):
    code, fake = run(["claim", "10"], gitlab([gl_issue(10, assignees=["kim"])]), config=config)
    assert code == board.REFUSED
    assert fake.writes() == []
    assert "held by kim" in capsys.readouterr().out


def test_claim_refuses_a_group_conflict_without_force(config, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "triage.json").write_text(json.dumps({"issues": {"10": {"groups": ["g"]}, "11": {"groups": ["g"]}}}), encoding="utf-8")
    routes = gitlab([gl_issue(10), gl_issue(11, assignees=["kim"])])
    code, fake = run(["claim", "10"], routes, config=config)
    assert code == board.REFUSED and fake.writes() == []


def test_claim_detects_a_race(capsys, config):
    routes = gitlab([gl_issue(10)], **{"issues/10 -X PUT": ok({}),
                                       "=glab api projects/:id/issues/10": ok(gl_issue(10, assignees=["me", "kim"]))})
    code, _ = run(["claim", "10"], routes, config=config)
    assert code == board.REFUSED
    assert "someone may have claimed it" in capsys.readouterr().out


def test_release_keeps_the_other_assignees(config):
    held = ok(gl_issue(10, assignees=["kim", "me"]))
    routes = gitlab([], **{"issues/10 -X PUT": ok({}), "=glab api projects/:id/issues/10": held})
    code, fake = run(["release", "10"], routes, config=config)
    assert code == board.OK
    assert fake.writes() == ["glab api projects/:id/issues/10 -X PUT -F assignee_ids=[100]"]


def test_two_current_milestones_is_an_error(capsys, config):
    routes = gitlab([], **{"milestones?state=active": ok([
        {"title": "A", "start_date": "2030-05-01", "due_date": "2030-05-31"},
        {"title": "B", "start_date": "2030-05-10", "due_date": "2030-05-20"}])})
    code, _ = run([], routes, config=config)
    assert code == board.ERROR
    assert "2 active milestones" in capsys.readouterr().out


def test_project_id_from_config_replaces_the_checkout(config):
    code, fake = run([], gitlab([]), cfg_text='[forge]\nproject = "42"\n' + CFG, config=config)
    assert code == board.OK
    assert any(c.startswith("glab api --paginate projects/42/issues") for c in fake.calls)


def gh_issue(n, labels=("bug",), assignees=(), pull=False):
    raw = {"number": n, "title": f"issue {n}", "state": "open", "labels": [{"name": label} for label in labels],
           "assignees": [{"login": a} for a in assignees], "user": {"login": "ann"}, "milestone": {"title": "v2"},
           "html_url": f"https://github.com/owner/repo/issues/{n}", "updated_at": "2030-05-01T00:00:00Z"}
    if pull:
        raw["pull_request"] = {}
    return raw


def github(issues, **over):
    routes = {
        "git remote get-url": (0, "https://github.com/owner/repo.git\n", ""),
        "git ls-remote": (0, "", ""),
        "=gh api user": ok({"login": "me"}),
        "milestones?state=all": ok([{"title": "v2", "number": 3}]),
        "issues?state=open": ok(issues),
        "pulls?state=open": ok([]),
    }
    routes.update(over)
    return routes


GH_CFG = '[filter]\nmilestone = "v2"\nlabels_any = ["bug"]\n'


def test_github_list_skips_pull_requests(capsys, config):
    code, fake = run([], github([gh_issue(1), gh_issue(2, pull=True)]), cfg_text=GH_CFG, config=config)
    assert code == board.OK
    out = capsys.readouterr().out
    assert "#1" in out and "#2" not in out
    assert any("issues?state=open&per_page=100&milestone=3" in c for c in fake.calls)


def test_github_claim_posts_the_assignee(config):
    routes = github([gh_issue(1)], **{"assignees -X POST": ok({}),
                                      "=gh api repos/owner/repo/issues/1": [ok(gh_issue(1)), ok(gh_issue(1, assignees=["me"]))]})
    code, fake = run(["claim", "1"], routes, cfg_text=GH_CFG, config=config)
    assert code == board.OK
    assert fake.writes() == ["gh api repos/owner/repo/issues/1/assignees -X POST -f assignees[]=me"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
