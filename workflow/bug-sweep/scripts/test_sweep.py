# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""Checks for sweep.py: remote parsing, config defaults and validation, paging, the backport target.

uv run test_sweep.py
"""
import sys
from pathlib import Path

import pytest

import sweep
from conftest import Fake

REMOTE = {"git remote get-url origin": (0, "git@git.example.com:group/project.git\n", "")}


@pytest.mark.parametrize("url, host, path", [
    ("git@git.example.com:group/project.git", "git.example.com", "group/project"),
    ("https://git.example.com/group/sub/project.git", "git.example.com", "group/sub/project"),
    ("ssh://git@git.example.com:2222/group/project", "git.example.com", "group/project"),
    ("https://github.com/owner/repo", "github.com", "owner/repo"),
    ("https://user@GitHub.com/owner/repo.git/", "github.com", "owner/repo"),
])
def test_parse_remote(url, host, path):
    assert sweep.parse_remote(url) == (host, path)


def test_config_path_mirrors_the_remote():
    assert sweep.config_path("github.com", "owner/repo") == Path("~/.config/bug-sweep/github.com/owner/repo.toml").expanduser()


def test_defaults_fill_missing_keys_and_forge_follows_the_host(config):
    cfg = sweep.load_config(Fake(REMOTE), config('[filter]\nlabels_any = ["bug"]\n'))
    assert cfg.kind == "gitlab"
    assert cfg["filter"]["labels_any"] == ["bug"]
    assert cfg["filter"]["unassigned"] is True
    assert cfg["merge"]["ask"] is True
    assert cfg["backport"]["mode"] == "never"


def test_github_host_selects_github(config):
    cfg = sweep.load_config(Fake({"git remote": (0, "https://github.com/owner/repo.git\n", "")}), config())
    assert cfg.kind == "github"


@pytest.mark.parametrize("text, message", [
    ("[filter]\nlabel = ['bug']\n", "unknown key"),
    ("[filters]\n", "unknown section"),
    ("[merge]\nask = 'no'\n", "must be bool"),
    ("[backport]\nmode = 'sometimes'\n", "expected one of"),
])
def test_bad_config_is_refused(config, text, message):
    with pytest.raises(sweep.SweepError, match=message):
        sweep.load_config(Fake(REMOTE), config(text))


@pytest.mark.parametrize("text, message", [
    ("[[merge.when]]\nplay_jobs = ['a']\n", r"when #1.paths must list"),
    ("[[merge.when]]\npaths = ['a']\n", "needs play_jobs or require_jobs"),
    ("[[merge.when]]\npaths = 'a'\nplay_jobs = ['a']\n", "paths must be a list of strings"),
    ("[[merge.when]]\npaths = ['a']\nrequire_jobs = [1]\n", "require_jobs must be a list of strings"),
    ("[[merge.when]]\npaths = ['a']\nrequire_jobs = ['a']\nbranch = 'x'\n", "unknown key.s. in merge.when #1: branch"),
    ("[merge]\nwhen = 'x'\n", "merge.when must be list"),
    ("[merge]\nwhen = ['x']\n", "merge.when #1 must be a table"),
])
def test_bad_merge_when_is_refused(config, text, message):
    with pytest.raises(sweep.SweepError, match=message):
        sweep.load_config(Fake(REMOTE), config(text))


@pytest.mark.parametrize("pattern, path, hit", [
    ("web/**", "web/a/b.js", True),
    ("web/**", "webapp/a.js", False),
    ("**/*.css", "a.css", True),
    ("**/*.css", "x/y/a.css", True),
    ("*.css", "x/a.css", False),
    ("src/*/page.js", "src/a/page.js", True),
    ("src/*/page.js", "src/a/b/page.js", False),
    ("a/**/z", "a/z", True),
    ("a/**/z", "a/b/c/z", True),
    ("v?.js", "v1.js", True),
    ("a.b", "axb", False),
])
def test_glob_regex(pattern, path, hit):
    assert bool(sweep.glob_regex(pattern).match(path)) is hit


WHEN = {"play_jobs": ["build"], "require_jobs": ["unit"], "when": [
    {"paths": ["web/**"], "play_jobs": ["e2e"], "require_jobs": ["e2e"]},
    {"paths": ["**/*.css"], "play_jobs": ["e2e", "visual"]}]}


def test_select_jobs_without_a_match_keeps_the_base():
    assert sweep.select_jobs(WHEN, ["docs/a.md"]) == (["build"], ["unit"])


def test_select_jobs_adds_one_match():
    assert sweep.select_jobs(WHEN, ["web/a.js"]) == (["build", "e2e"], ["unit", "e2e"])


def test_select_jobs_joins_two_matches_and_drops_repeats():
    assert sweep.select_jobs(WHEN, ["web/a.js", "x/b.css"]) == (["build", "e2e", "visual"], ["unit", "e2e"])


def test_select_jobs_with_no_changed_files_keeps_the_base():
    assert sweep.select_jobs(WHEN, []) == (["build"], ["unit"])


def test_gitlab_changed_files_pages_and_keeps_a_rename_under_both_names(config):
    cfg = sweep.load_config(Fake(REMOTE), config())
    fake = Fake({"merge_requests/5/diffs": (0, '[{"new_path": "b.js", "old_path": "a.js"}]\n[{"new_path": "c.js", "old_path": "c.js"}]', "")})
    assert sweep.GitLab(cfg, fake).changed_files(5) == ["b.js", "a.js", "c.js"]
    assert fake.calls == ["glab api --paginate projects/:id/merge_requests/5/diffs?per_page=100"]


def test_missing_config_names_the_expected_path():
    with pytest.raises(sweep.SweepError, match=r"bug-sweep.git\.example\.com.group.project\.toml"):
        sweep.load_config(Fake(REMOTE))


def test_call_joins_concatenated_pages():
    fake = Fake({"glab api": (0, '[{"a": 1}]\n[{"a": 2}]', "")})
    assert sweep.call(fake, ["glab", "api", "--paginate", "x"]) == [{"a": 1}, {"a": 2}]


def test_call_failure_carries_the_status():
    fake = Fake({"glab api": (1, "", "glab: 404 Not found (HTTP 404)")})
    with pytest.raises(sweep.SweepError, match="HTTP 404"):
        sweep.call(fake, ["glab", "api", "x"])


def issue(milestone="Cycle 12", labels=("bug",)):
    return sweep.Issue(5, "t", "open", list(labels), [], "a", milestone, "u", "")


BACKPORT = '[backport]\nmode = "ask"\nmilestone = "Cycle {n}"\nbranch = "release/{n}"\n'


def test_backport_target_from_the_milestone(config):
    cfg = sweep.load_config(Fake(REMOTE), config(BACKPORT))
    assert sweep.backport_target(cfg, issue(), ["main", "release/12"]) == ("release/12", "")


def test_backport_target_needs_the_branch_on_the_remote(config):
    cfg = sweep.load_config(Fake(REMOTE), config(BACKPORT))
    assert sweep.backport_target(cfg, issue(), ["main"]) == ("", "release/12 does not exist on the remote")


def test_backport_target_needs_a_matching_milestone(config):
    cfg = sweep.load_config(Fake(REMOTE), config(BACKPORT))
    target, why = sweep.backport_target(cfg, issue(milestone="Backlog"), ["release/12"])
    assert target == "" and "does not match" in why


def test_mentions_ignores_longer_numbers_and_request_refs():
    assert sweep.mentions(12, "fix/12-thing")
    assert not sweep.mentions(12, "fix/123-thing")
    assert not sweep.mentions(12, "follows !12")


def test_wanted_applies_every_label_rule():
    flt = {"labels_any": ["bug", "defect"], "labels_all": ["triaged"], "exclude_labels": ["wontfix"],
           "exclude_authors": ["bot"], "unassigned": True}
    assert sweep.wanted(issue(labels=("bug", "triaged")), flt, "Cycle 12")
    assert not sweep.wanted(issue(labels=("bug",)), flt, "Cycle 12")
    assert not sweep.wanted(issue(labels=("bug", "triaged", "wontfix")), flt, "Cycle 12")
    assert not sweep.wanted(issue(labels=("bug", "triaged")), flt, "Cycle 13")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
