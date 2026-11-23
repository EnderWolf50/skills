# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Checks for merge_pr.py with glab, gh and git mocked: when it merges, waits, blocks, and what it sends.

uv run test_merge_pr.py
"""
import json
import sys

import pytest

import merge_pr

SHA = "a" * 40
NEW = "b" * 40
ERR404 = (1, '{"message":"404 Not found"}', "glab: 404 Not found (HTTP 404)")


def ok(body):
    return (0, json.dumps(body), "")


class Fake:
    """Answers each command from the first route whose key is a substring of it (a key starting with `=` must match the
    whole command); a list answers in turn, its last item repeating."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, cmd):
        line = " ".join(cmd)
        self.calls.append(line)
        for key, answer in self.routes.items():
            if (line == key[1:]) if key.startswith("=") else (key in line):
                if isinstance(answer, list):
                    return answer.pop(0) if len(answer) > 1 else answer[0]
                return answer
        raise AssertionError(f"unexpected command: {line}")

    def merges(self):
        return [c for c in self.calls if "/merge " in c + " " and "PUT" in c]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run(argv, routes):
    fake, clock = Fake(routes), Clock()
    code = merge_pr.main(argv, run=fake, sleep=clock.sleep, clock=clock)
    return code, fake


def mr(sha=SHA, status="mergeable", pipe="success", state="opened", target="master"):
    head_pipeline = None if pipe is None else {"id": 7, "sha": sha, "status": pipe}
    return ok({"sha": sha, "state": state, "detailed_merge_status": status, "head_pipeline": head_pipeline,
               "target_branch": target})


def gitlab(**over):
    """Routes for a GitLab checkout; the MR read comes last so it never answers the merge or a sub-resource."""
    routes = {
        "git remote": (0, "git@git.example.com:group/project.git\n", ""),
        "=glab api projects/:id": ok({"default_branch": "master", "ci_config_path": ""}),
        "merge_requests/5/merge": ok({"state": "merged", "merge_commit_sha": "c" * 40}),
        "closes_issues": (0, '{"iid": 9, "state": "closed"}\n', ""),
    }
    read = over.pop("merge_requests/5", mr())
    routes.update(over)
    routes["merge_requests/5"] = read
    return routes


def test_gitlab_merges_a_green_mergeable_head_pinned_to_its_sha(capsys):
    code, fake = run(["5", "--sha", SHA], gitlab())
    assert code == merge_pr.MERGED
    assert fake.merges() == [f"glab api projects/:id/merge_requests/5/merge -X PUT -f sha={SHA}"]
    out = capsys.readouterr().out
    assert "merged aaaaaaaaaa into master as cccccccccc" in out
    assert "issue #9: closed" in out


def test_without_sha_it_pins_the_first_head_it_reads(capsys):
    code, fake = run(["5"], gitlab())
    assert code == merge_pr.MERGED
    assert f"pinned to head {SHA}" in capsys.readouterr().out
    assert f"sha={SHA}" in fake.merges()[0]


def test_dry_run_never_merges(capsys):
    code, fake = run(["5", "--dry-run"], gitlab())
    assert code == merge_pr.MERGED
    assert fake.merges() == []
    assert "dry run" in capsys.readouterr().out


def test_a_head_pushed_after_the_check_blocks():
    code, fake = run(["5", "--sha", SHA], gitlab(**{"merge_requests/5": mr(sha=NEW)}))
    assert code == merge_pr.BLOCKED
    assert fake.merges() == []


def test_a_short_sha_is_refused_before_any_call():
    with pytest.raises(SystemExit):
        merge_pr.main(["5", "--sha", "abc123"], run=Fake({}))


def test_another_target_branch_blocks():
    code, fake = run(["5", "--target", "release/sprint-163"], gitlab())
    assert code == merge_pr.BLOCKED
    assert fake.merges() == []


@pytest.mark.parametrize("pipe, status", [("failed", "ci_must_pass"), ("canceled", "ci_must_pass"),
                                          ("manual", "ci_must_pass"), ("success", "conflict"),
                                          ("success", "need_rebase"), ("success", "not_approved"),
                                          ("success", "something_new")])
def test_states_that_waiting_cannot_fix_block_on_the_first_read(pipe, status):
    code, fake = run(["5"], gitlab(**{"merge_requests/5": mr(pipe=pipe, status=status)}))
    assert code == merge_pr.BLOCKED
    assert sum("merge_requests/5" in c for c in fake.calls) == 1
    assert fake.merges() == []


def test_a_running_pipeline_is_waited_for_then_merged():
    reads = [mr(pipe="running", status="ci_still_running")] * 3 + [mr()]
    code, fake = run(["5", "--interval", "5"], gitlab(**{"merge_requests/5": reads}))
    assert code == merge_pr.MERGED
    assert len(fake.merges()) == 1


def test_a_pipeline_still_running_at_the_timeout_exits_3(capsys):
    code, fake = run(["5", "--timeout", "20"], gitlab(**{"merge_requests/5": mr(pipe="pending", status="ci_must_pass")}))
    assert code == merge_pr.TIMED_OUT
    assert fake.merges() == []
    assert "pipeline 7 pending" in capsys.readouterr().out


def test_no_pipeline_in_a_repo_without_ci_config_merges():
    code, fake = run(["5"], gitlab(**{"merge_requests/5": mr(pipe=None), "repository/files": ERR404}))
    assert code == merge_pr.MERGED


def test_no_pipeline_in_a_repo_with_ci_config_waits_and_says_why(capsys):
    code, fake = run(["5", "--timeout", "10"],
                     gitlab(**{"merge_requests/5": mr(pipe=None, status="ci_must_pass"), "repository/files": ok({})}))
    assert code == merge_pr.TIMED_OUT
    assert "no pipeline for this head yet" in capsys.readouterr().out


def test_allow_no_pipeline_skips_the_ci_config_lookup():
    code, fake = run(["5", "--allow-no-pipeline"], gitlab(**{"merge_requests/5": mr(pipe=None)}))
    assert code == merge_pr.MERGED
    assert not any("repository/files" in c for c in fake.calls)


@pytest.mark.parametrize("jobs, expected", [
    ('{"name": "unit", "status": "success"}\n', merge_pr.MERGED),
    ('{"name": "unit", "status": "manual"}\n', merge_pr.BLOCKED),
    ('{"name": "unit", "status": "failed"}\n', merge_pr.BLOCKED),
    ('{"name": "other", "status": "success"}\n', merge_pr.BLOCKED),
])
def test_a_required_job_must_have_run_and_passed(jobs, expected):
    code, fake = run(["5", "--require-job", "unit"], gitlab(**{"pipelines/7/jobs": (0, jobs, "")}))
    assert code == expected


def test_a_required_job_not_yet_listed_waits_while_the_pipeline_runs(capsys):
    reads = [mr(pipe="running", status="ci_still_running"), mr()]
    jobs = [(0, "", ""), (0, '{"name": "unit", "status": "success"}\n', "")]
    code, fake = run(["5", "--require-job", "unit"], gitlab(**{"merge_requests/5": reads, "pipelines/7/jobs": jobs}))
    assert code == merge_pr.MERGED
    assert "has not appeared yet" in capsys.readouterr().out


def test_a_409_on_merge_blocks_as_a_moved_head():
    refusal = (1, '{"message":"SHA does not match HEAD of source branch"}', "glab: 409 Conflict (HTTP 409)")
    code, fake = run(["5"], gitlab(**{"merge_requests/5/merge": refusal}))
    assert code == merge_pr.BLOCKED
    assert len(fake.merges()) == 1


def test_a_refusal_is_retried_and_its_message_shown(capsys):
    refusal = (1, '{"message":"405 Method Not Allowed"}', "glab: 405 Method Not Allowed (HTTP 405)")
    code, fake = run(["5", "--timeout", "10"], gitlab(**{"merge_requests/5/merge": refusal}))
    assert code == merge_pr.REFUSED
    assert len(fake.merges()) == 3
    assert "405 Method Not Allowed" in capsys.readouterr().out


def test_a_failed_read_exits_1_with_the_server_message(capsys):
    code, fake = run(["5"], gitlab(**{"merge_requests/5": ERR404}))
    assert code == merge_pr.ERROR
    assert "404 Not found" in capsys.readouterr().out


def test_a_release_target_says_issues_stay_open(capsys):
    code, _ = run(["5"], gitlab(**{"merge_requests/5": mr(target="release/sprint-163")}))
    assert code == merge_pr.MERGED
    assert "not the default branch" in capsys.readouterr().out


def test_gitlab_has_no_rebase_method():
    code, fake = run(["5", "--method", "rebase"], gitlab())
    assert code == merge_pr.ERROR


def test_squash_is_sent_to_gitlab():
    code, fake = run(["5", "--method", "squash"], gitlab())
    assert fake.merges()[0].endswith("-f squash=true")


# ---------------------------------------------------------------- GitHub

def run_check(name="check", conclusion="SUCCESS", status="COMPLETED"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def pr(sha=SHA, state="OPEN", draft=False, mergeable="MERGEABLE", merge_state="CLEAN", review="", checks=None,
       base="main"):
    return ok({"number": 3, "state": state, "isDraft": draft, "headRefOid": sha, "baseRefName": base,
               "mergeable": mergeable, "mergeStateStatus": merge_state, "reviewDecision": review,
               "statusCheckRollup": [run_check()] if checks is None else checks})


def github(**over):
    routes = {
        "git remote": (0, "https://github.com/me/tool.git\n", ""),
        "pulls/3/merge": ok({"sha": "d" * 40, "merged": True, "message": "Pull Request successfully merged"}),
        "closingIssuesReferences": ok({"closingIssuesReferences": [
            {"number": 4, "repository": {"name": "tool", "owner": {"login": "me"}}}]}),
        "repos/me/tool/issues/4": ok({"state": "closed"}),
        "=gh api repos/{owner}/{repo}": ok({"default_branch": "main"}),
        "pr view 3 --json number": pr(),
    }
    routes.update(over)
    return routes


def test_github_merges_with_the_pinned_sha_and_method(capsys):
    code, fake = run(["3", "--sha", SHA, "--method", "squash"], github())
    assert code == merge_pr.MERGED
    assert fake.merges() == [f"gh api repos/{{owner}}/{{repo}}/pulls/3/merge -X PUT -f sha={SHA} -f merge_method=squash"]
    assert "issue me/tool#4: closed" in capsys.readouterr().out


@pytest.mark.parametrize("pr_answer", [
    pr(checks=[run_check(conclusion="FAILURE")]),
    pr(checks=[{"__typename": "StatusContext", "context": "ci", "state": "ERROR"}]),
    pr(draft=True),
    pr(mergeable="CONFLICTING", merge_state="DIRTY"),
    pr(merge_state="BEHIND"),
    pr(merge_state="BLOCKED", review="REVIEW_REQUIRED"),
    pr(state="MERGED"),
])
def test_github_states_that_block(pr_answer):
    code, fake = run(["3"], github(**{"pr view 3 --json number": pr_answer}))
    assert code == merge_pr.BLOCKED
    assert fake.merges() == []


def test_github_waits_for_running_checks_then_merges():
    reads = [pr(checks=[run_check(status="IN_PROGRESS", conclusion="")], merge_state="BLOCKED")] * 2 + [pr()]
    code, fake = run(["3"], github(**{"pr view 3 --json number": reads}))
    assert code == merge_pr.MERGED


def test_github_repo_without_workflows_merges_without_checks():
    code, fake = run(["3"], github(**{"pr view 3 --json number": pr(checks=[]),
                                      "contents/.github/workflows": (1, '{"message":"Not Found"}', "gh: Not Found (HTTP 404)")}))
    assert code == merge_pr.MERGED


def test_github_repo_with_workflows_waits_for_checks_to_appear():
    code, fake = run(["3", "--timeout", "10"], github(**{"pr view 3 --json number": pr(checks=[]),
                                                          "contents/.github/workflows": ok([])}))
    assert code == merge_pr.TIMED_OUT


def test_github_required_check_missing_from_a_finished_rollup_blocks():
    code, fake = run(["3", "--require-job", "e2e"], github())
    assert code == merge_pr.BLOCKED


def test_repo_flag_targets_another_github_repo():
    routes = github()
    routes = {k.replace("{owner}/{repo}", "me/tool"): v for k, v in routes.items()}
    code, fake = run(["3", "--repo", "me/tool", "--forge", "github"], routes)
    assert code == merge_pr.MERGED
    assert any(c.endswith("-R me/tool") for c in fake.calls if "pr view" in c)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
