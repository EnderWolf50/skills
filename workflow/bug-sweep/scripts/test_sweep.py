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
