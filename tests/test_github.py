"""
Tests for gitlogstats.github. A fake `gh` executable (tests/fake_gh.py) stands
in for the GitHub CLI, so no test touches the network.
"""

import datetime
import os
import time

import pytest

from fake_gh import install_fake_gh
from gitlogstats import github
from gitlogstats.github import (
    GitHubError,
    GitHubUnavailable,
    check_gh,
    commit_login,
    contributor_logins,
    count_pull_requests,
    fetch_pull_requests,
    gh_api,
    github_repo_from_url,
    user_profile,
)

REPO = "acme/widgets"
PULLS = f"repos/{REPO}/pulls?state=all&per_page=100"
PAGES = ["pulls_page1.json", "pulls_page2.json"]


def pulls_routes(shape):
    return {PULLS: {"pages": PAGES, "shape": shape}}


def utc_z(local_dt):
    """The GitHub-style UTC timestamp for a naive local datetime."""
    return datetime.datetime.utcfromtimestamp(
        time.mktime(local_dt.timetuple())
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_pr(login="u", created=None, merged=None, closed=None, state=None, base="main"):
    if state is None:
        state = "closed" if (merged or closed) else "open"
    return {
        "login": login,
        "user_type": "User",
        "state": state,
        "created_at": created,
        "merged_at": merged,
        "closed_at": closed,
        "base": base,
    }


# ─── check_gh ────────────────────────────────────────────────────────────────


def test_fieldnames():
    assert github.GITHUB_FIELDNAMES == [
        "github_username",
        "prs_opened",
        "prs_merged",
        "prs_closed_unmerged",
    ]


def test_check_gh_signed_in(tmp_path, monkeypatch):
    calls = install_fake_gh(tmp_path, monkeypatch)
    assert check_gh() is None
    assert calls() == [["auth", "status"]]


def test_check_gh_signed_out(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, auth_ok=False)
    with pytest.raises(GitHubUnavailable) as info:
        check_gh()
    assert str(info.value) == (
        "gitlogstats: --github needs the GitHub CLI (gh) to be signed in. "
        "Run 'gh auth login', or run without --github."
    )


def test_check_gh_not_installed(monkeypatch):
    monkeypatch.setattr(github.shutil, "which", lambda name: None)
    with pytest.raises(GitHubUnavailable) as info:
        check_gh()
    assert str(info.value) == (
        "gitlogstats: --github needs the GitHub CLI (gh), which is not installed. "
        "Install it from https://cli.github.com and run 'gh auth login', "
        "or run without --github."
    )


def test_check_gh_not_installed_empty_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(GitHubUnavailable, match="not installed"):
        check_gh()


# ─── github_repo_from_url ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/o/r",
        "https://github.com/o/r.git",
        "https://github.com/o/r/",
        "https://github.com/o/r.git/",
        "http://github.com/o/r",
        "https://www.github.com/o/r",
        "https://GitHub.COM/o/r",
        "git@github.com:o/r.git",
        "git@github.com:o/r",
        "ssh://git@github.com/o/r.git",
        "ssh://github.com/o/r",
        "https://user@github.com/o/r",
        "https://user:token@github.com/o/r.git",
        "  https://github.com/o/r\n",
        "https://github.com/o/r?tab=readme",
        "https://github.com/o/r/#readme",
    ],
)
def test_github_url_forms(url):
    assert github_repo_from_url(url) == "o/r"


def test_github_url_keeps_dots_and_case_in_names():
    assert github_repo_from_url("https://github.com/My-Org/my.repo.git") == (
        "My-Org/my.repo"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/o/r",
        "git@gitlab.com:o/r.git",
        "/home/me/code/r",
        "relative/path/r",
        ".",
        "https://github.com.evil.com/o/r",
        "https://notgithub.com/o/r",
        "https://evil.com/github.com/o/r",
        "git@github.com.evil.com:o/r.git",
        "https://github.com/o",
        "https://github.com/o/",
        "https://github.com/",
        "https://github.com",
        "git@github.com:o",
        "https://github.com/o/r/extra",
        "",
    ],
)
def test_non_github_urls(url):
    assert github_repo_from_url(url) is None


# ─── gh_api and pagination ───────────────────────────────────────────────────


@pytest.mark.parametrize("shape", ["merged", "newline", "concatenated"])
def test_pagination_shapes(tmp_path, monkeypatch, shape):
    calls = install_fake_gh(tmp_path, monkeypatch, pulls_routes(shape))
    result = gh_api(PULLS, paginate=True)
    assert [pr["number"] for pr in result] == [1, 2, 3, 4, 5]
    assert calls() == [["api", PULLS, "--paginate"]]


def test_gh_api_without_pagination_has_no_flag(tmp_path, monkeypatch):
    calls = install_fake_gh(
        tmp_path, monkeypatch, {"users/alice-dev": {"pages": ["user_full.json"]}}
    )
    assert gh_api("users/alice-dev")["login"] == "alice-dev"
    assert calls() == [["api", "users/alice-dev"]]


def test_gh_api_empty_output_is_empty_list(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, {"p": {"pages": []}})
    assert gh_api("p", paginate=True) == []


def test_gh_api_error_includes_stderr(tmp_path, monkeypatch):
    install_fake_gh(
        tmp_path,
        monkeypatch,
        {"repos/a/b": {"error": "gh: Not Found (HTTP 404)\n", "stdout": "{}"}},
    )
    with pytest.raises(GitHubError) as info:
        gh_api("repos/a/b")
    assert str(info.value) == "gh: Not Found (HTTP 404)"


def test_gh_api_error_without_stderr(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, {"p": {"error": ""}})
    with pytest.raises(GitHubError, match="gh api p failed"):
        gh_api("p")


def test_gh_api_invalid_json_is_github_error(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, {"p": {"raw": "<html>oops</html>"}})
    with pytest.raises(GitHubError, match="gh api p returned invalid JSON"):
        gh_api("p")


def test_gh_api_unknown_path_is_404(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch)
    with pytest.raises(GitHubError, match="HTTP 404"):
        gh_api("nothing")


def test_parse_json_stream_variants():
    parse = github._parse_json_stream
    assert parse("") == []
    assert parse("[1][2,3]") == [1, 2, 3]
    assert parse("[1]\n[2]\n") == [1, 2]
    assert parse('{"a": 1}') == {"a": 1}
    assert parse('{"a": 1}\n{"b": 2}') == [{"a": 1}, {"b": 2}]


# ─── fetch_pull_requests ─────────────────────────────────────────────────────


def test_fetch_pull_requests_fields(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, pulls_routes("merged"))
    prs = fetch_pull_requests(REPO)
    assert len(prs) == 5
    assert prs[0] == {
        "login": "alice-dev",
        "user_type": "User",
        "state": "closed",
        "created_at": "2026-03-02T15:04:05Z",
        "merged_at": "2026-03-03T10:00:00Z",
        "closed_at": "2026-03-03T10:00:00Z",
        "base": "main",
    }
    assert prs[1]["merged_at"] is None and prs[1]["state"] == "open"


def test_fetch_pull_requests_ghost_and_bot(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, pulls_routes("newline"))
    prs = fetch_pull_requests(REPO)
    assert prs[3]["login"] == "ghost" and prs[3]["user_type"] is None
    assert prs[4]["login"] == "dependabot[bot]" and prs[4]["user_type"] == "Bot"


def test_fetch_pull_requests_error(tmp_path, monkeypatch):
    install_fake_gh(
        tmp_path,
        monkeypatch,
        {PULLS: {"error": "gh: API rate limit exceeded (HTTP 403)\n"}},
    )
    with pytest.raises(GitHubError, match="rate limit"):
        fetch_pull_requests(REPO)


def test_fetch_pull_requests_single_page(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, {PULLS: {"pages": ["pulls_page1.json"]}})
    assert fetch_pull_requests(REPO)[0]["base"] == "main"


# ─── count_pull_requests ─────────────────────────────────────────────────────

START, END = "03/01/2026", "03/31/2026"
D = datetime.datetime


def count_one(pr, start=START, end=END, branch=None):
    return count_pull_requests([pr], start, end, branch)["u"]


def test_counts_from_fixture_prs(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, pulls_routes("merged"))
    prs = fetch_pull_requests(REPO)
    # created_at near month edges is irrelevant here: use a very wide range
    counts = count_pull_requests(prs, "01/01/2020", "12/31/2030")
    assert counts == {
        "alice-dev": {"prs_opened": 1, "prs_merged": 1, "prs_closed_unmerged": 0},
        "bob-codes": {"prs_opened": 2, "prs_merged": 0, "prs_closed_unmerged": 1},
        "ghost": {"prs_opened": 1, "prs_merged": 0, "prs_closed_unmerged": 1},
        "dependabot[bot]": {"prs_opened": 1, "prs_merged": 1, "prs_closed_unmerged": 0},
    }


def test_open_pr_is_only_opened():
    pr = make_pr(created=utc_z(D(2026, 3, 10, 12)))
    assert count_one(pr) == {
        "prs_opened": 1,
        "prs_merged": 0,
        "prs_closed_unmerged": 0,
    }


def test_merged_pr_is_not_closed_unmerged():
    pr = make_pr(
        created=utc_z(D(2026, 3, 10, 12)),
        merged=utc_z(D(2026, 3, 11, 12)),
        closed=utc_z(D(2026, 3, 11, 12)),
    )
    assert count_one(pr) == {
        "prs_opened": 1,
        "prs_merged": 1,
        "prs_closed_unmerged": 0,
    }


def test_closed_unmerged_pr():
    pr = make_pr(
        created=utc_z(D(2026, 3, 10, 12)),
        closed=utc_z(D(2026, 3, 11, 12)),
        state="closed",
    )
    assert count_one(pr) == {
        "prs_opened": 1,
        "prs_merged": 0,
        "prs_closed_unmerged": 1,
    }


def test_merged_in_range_but_created_before():
    pr = make_pr(
        created=utc_z(D(2026, 2, 10, 12)),
        merged=utc_z(D(2026, 3, 11, 12)),
        closed=utc_z(D(2026, 3, 11, 12)),
    )
    assert count_one(pr) == {
        "prs_opened": 0,
        "prs_merged": 1,
        "prs_closed_unmerged": 0,
    }


def test_closed_unmerged_needs_closed_at_in_range():
    pr = make_pr(
        created=utc_z(D(2026, 3, 10, 12)),
        closed=utc_z(D(2026, 4, 2, 12)),
        state="closed",
    )
    assert count_one(pr)["prs_closed_unmerged"] == 0


def test_closed_state_without_closed_at_is_not_counted():
    pr = make_pr(created=utc_z(D(2026, 3, 10, 12)), state="closed")
    assert count_one(pr)["prs_closed_unmerged"] == 0


def test_outside_range_gives_zero_row():
    pr = make_pr(created=utc_z(D(2025, 1, 1, 12)))
    assert count_one(pr) == {
        "prs_opened": 0,
        "prs_merged": 0,
        "prs_closed_unmerged": 0,
    }


@pytest.mark.parametrize(
    "local_time, expected",
    [
        (D(2026, 2, 28, 23, 59, 59), 0),
        (D(2026, 3, 1, 0, 0, 0), 1),
        (D(2026, 3, 31, 23, 59, 59), 1),
        (D(2026, 4, 1, 0, 0, 0), 0),
    ],
)
def test_date_boundaries_for_each_count(local_time, expected):
    z = utc_z(local_time)
    opened = count_one(make_pr(created=z))
    merged = count_one(make_pr(created=utc_z(D(2020, 1, 1)), merged=z, closed=z))
    closed = count_one(make_pr(created=utc_z(D(2020, 1, 1)), closed=z, state="closed"))
    assert opened["prs_opened"] == expected
    assert merged["prs_merged"] == expected
    assert closed["prs_closed_unmerged"] == expected


def test_single_day_range():
    pr = make_pr(created=utc_z(D(2026, 3, 5, 23, 59, 59)))
    assert count_one(pr, "03/05/2026", "03/05/2026")["prs_opened"] == 1


def test_boundaries_in_non_utc_timezone(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on this platform")
    monkeypatch.setenv("TZ", "Pacific/Auckland")  # UTC+12/+13, never UTC
    time.tzset()
    try:
        first = utc_z(D(2026, 3, 1, 0, 0, 0))
        before = utc_z(D(2026, 2, 28, 23, 59, 59))
        last = utc_z(D(2026, 3, 31, 23, 59, 59))
        after = utc_z(D(2026, 4, 1, 0, 0, 0))
        # In Auckland the local start of March 1st is still Feb 28th in UTC.
        assert first.startswith("2026-02-28")
        assert count_one(make_pr(created=first))["prs_opened"] == 1
        assert count_one(make_pr(created=before))["prs_opened"] == 0
        assert count_one(make_pr(created=last))["prs_opened"] == 1
        assert count_one(make_pr(created=after))["prs_opened"] == 0
    finally:
        monkeypatch.undo()
        time.tzset()


def test_utc_timestamp_converts_to_local_day(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on this platform")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        # 2026-04-01T03:00Z is still March 31st in Los Angeles
        pr = make_pr(created="2026-04-01T03:00:00Z")
        assert count_one(pr)["prs_opened"] == 1
    finally:
        monkeypatch.undo()
        time.tzset()


def test_branch_filter():
    prs = [
        make_pr("a", created=utc_z(D(2026, 3, 10, 12)), base="main"),
        make_pr("b", created=utc_z(D(2026, 3, 10, 12)), base="develop"),
        make_pr("a", created=utc_z(D(2026, 3, 11, 12)), base="develop"),
    ]
    assert count_pull_requests(prs, START, END)["a"]["prs_opened"] == 2
    only_main = count_pull_requests(prs, START, END, branch="main")
    assert only_main == {
        "a": {"prs_opened": 1, "prs_merged": 0, "prs_closed_unmerged": 0}
    }
    assert count_pull_requests(prs, START, END, branch="nope") == {}


def test_ghost_and_bot_counted_like_others(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, pulls_routes("merged"))
    counts = count_pull_requests(fetch_pull_requests(REPO), "01/01/2020", "12/31/2030")
    assert counts["ghost"]["prs_opened"] == 1
    assert counts["dependabot[bot]"]["prs_merged"] == 1


def test_no_prs_gives_empty_counts():
    assert count_pull_requests([], START, END) == {}


# ─── commit_login, user_profile, contributor_logins ──────────────────────────


def test_commit_login_linked(tmp_path, monkeypatch):
    sha = "1" * 40
    calls = install_fake_gh(
        tmp_path,
        monkeypatch,
        {f"repos/{REPO}/commits/{sha}": {"pages": ["commit_linked.json"]}},
    )
    assert commit_login(REPO, sha) == "alice-dev"
    assert calls() == [["api", f"repos/{REPO}/commits/{sha}"]]


def test_commit_login_unlinked_author_is_none(tmp_path, monkeypatch):
    sha = "2" * 40
    install_fake_gh(
        tmp_path,
        monkeypatch,
        {f"repos/{REPO}/commits/{sha}": {"pages": ["commit_unlinked.json"]}},
    )
    assert commit_login(REPO, sha) is None


@pytest.mark.parametrize(
    "stderr",
    [
        "gh: No commit found for SHA: abc (HTTP 422)\n",
        "gh: Not Found (HTTP 404)\n",
    ],
)
def test_commit_login_not_on_github_is_none(tmp_path, monkeypatch, stderr):
    sha = "3" * 40
    install_fake_gh(
        tmp_path, monkeypatch, {f"repos/{REPO}/commits/{sha}": {"error": stderr}}
    )
    assert commit_login(REPO, sha) is None


def test_commit_login_other_errors_raise(tmp_path, monkeypatch):
    sha = "4" * 40
    install_fake_gh(
        tmp_path,
        monkeypatch,
        {
            f"repos/{REPO}/commits/{sha}": {
                "error": "gh: API rate limit exceeded (HTTP 403)\n"
            }
        },
    )
    with pytest.raises(GitHubError, match="rate limit"):
        commit_login(REPO, sha)


def test_user_profile(tmp_path, monkeypatch):
    install_fake_gh(
        tmp_path,
        monkeypatch,
        {
            "users/alice-dev": {"pages": ["user_full.json"]},
            "users/bob-codes": {"pages": ["user_private.json"]},
        },
    )
    assert user_profile("alice-dev") == {
        "login": "alice-dev",
        "name": "Alice Example",
        "email": "alice@example.com",
    }
    assert user_profile("bob-codes") == {
        "login": "bob-codes",
        "name": None,
        "email": None,
    }


def test_user_profile_error(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch)
    with pytest.raises(GitHubError):
        user_profile("nobody")


@pytest.mark.parametrize("shape", ["merged", "newline", "concatenated"])
def test_contributor_logins(tmp_path, monkeypatch, shape):
    path = f"repos/{REPO}/contributors?per_page=100"
    install_fake_gh(
        tmp_path,
        monkeypatch,
        {
            path: {
                "pages": ["contributors.json", "contributors_page2.json"],
                "shape": shape,
            }
        },
    )
    assert contributor_logins(REPO) == {"alice-dev", "bob-codes", "carol-writes"}


def test_contributor_logins_empty_repository(tmp_path, monkeypatch):
    path = f"repos/{REPO}/contributors?per_page=100"
    install_fake_gh(tmp_path, monkeypatch, {path: {"pages": []}})
    assert contributor_logins(REPO) == set()
