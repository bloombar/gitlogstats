"""
Tests for gitlogstats.github. A fake `gh` executable (tests/fake_gh.py) stands
in for the GitHub CLI, so no test touches the network.
"""

import datetime
import json
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
    event_days,
    fetch_pull_requests,
    gh_api,
    github_repo_from_url,
    local_day,
    user_profile,
)

REPO = "acme/widgets"
GRAPHQL = f"graphql:{REPO}"
CONTRIBUTORS = f"repos/{REPO}/contributors?per_page=100"
CONTRIBUTOR_PAGES = ["contributors.json", "contributors_page2.json"]


def pulls_routes():
    """The two fixture pages of pull requests, served as gh --paginate prints."""
    return {GRAPHQL: {"graphql_pages": ["pulls_page1.json", "pulls_page2.json"]}}


def utc_z(local_dt):
    """The GitHub-style UTC timestamp for a naive local datetime."""
    return datetime.datetime.utcfromtimestamp(
        time.mktime(local_dt.timetuple())
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_pr(
    login="u",
    created=None,
    merged=None,
    closed=None,
    state=None,
    base="main",
    merged_by=None,
):
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
        "merged_by": merged_by,
    }


# ─── check_gh ────────────────────────────────────────────────────────────────


def test_fieldnames():
    assert github.GITHUB_FIELDNAMES == [
        "github_username",
        "prs_opened",
        "prs_merged",
        "prs_closed_unmerged",
        "prs_self_merged",
    ]


def test_email_fieldnames():
    assert github.EMAIL_FIELDNAMES == ["git_email", "github_email"]


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
    routes = {CONTRIBUTORS: {"pages": CONTRIBUTOR_PAGES, "shape": shape}}
    calls = install_fake_gh(tmp_path, monkeypatch, routes)
    result = gh_api(CONTRIBUTORS, paginate=True)
    assert [c["login"] for c in result] == ["alice-dev", "bob-codes", "carol-writes"]
    assert calls() == [["api", CONTRIBUTORS, "--paginate"]]


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


def node(author="u", kind="User", merger=None, state="OPEN", **fields):
    """A pull request as GraphQL returns it; merger is a (login, type) pair."""
    return {
        "author": {"login": author, "__typename": kind} if author else None,
        "mergedBy": {"login": merger[0], "__typename": merger[1]} if merger else None,
        "state": state,
        "createdAt": None,
        "mergedAt": None,
        "closedAt": None,
        "baseRefName": "main",
        **fields,
    }


def graphql_route(*pages):
    return {GRAPHQL: {"graphql_pages": list(pages)}}


def test_fetch_pull_requests_fields(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, pulls_routes())
    prs = fetch_pull_requests(REPO)
    assert len(prs) == 6
    assert prs[0] == {
        "login": "alice-dev",
        "user_type": "User",
        "state": "closed",
        "created_at": "2026-03-02T15:04:05Z",
        "merged_at": "2026-03-03T10:00:00Z",
        "closed_at": "2026-03-03T10:00:00Z",
        "base": "main",
        "merged_by": "alice-dev",
        "merge_commit": "abc123",
        "merge_committed_at": "2026-03-03T09:59:55Z",
    }
    assert prs[1]["merge_commit"] is None and prs[1]["merge_committed_at"] is None
    assert prs[1]["merged_at"] is None and prs[1]["state"] == "open"
    assert prs[1]["merged_by"] is None
    assert prs[2]["state"] == "closed" and prs[2]["base"] == "develop"
    assert prs[5]["login"] == "alice-dev" and prs[5]["merged_by"] == "bob-codes"


def test_fetch_pull_requests_ghost_and_bot(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, pulls_routes())
    prs = fetch_pull_requests(REPO)
    assert prs[3]["login"] == "ghost" and prs[3]["user_type"] is None
    # GraphQL says "dependabot" with type Bot; REST said "dependabot[bot]"
    assert prs[4]["login"] == "dependabot[bot]" and prs[4]["user_type"] == "Bot"
    assert prs[4]["merged_by"] == "dependabot[bot]"


def test_fetch_pull_requests_passes_variables_as_arguments(tmp_path, monkeypatch):
    calls = install_fake_gh(tmp_path, monkeypatch, pulls_routes())
    fetch_pull_requests(REPO)
    (call,) = calls()
    assert call[:3] == ["api", "graphql", "--paginate"]
    # every field is a raw string (-f), never a typed field (-F)
    assert "-F" not in call
    pairs = {call[i + 1].split("=", 1)[0] for i, a in enumerate(call) if a == "-f"}
    assert pairs == {"query", "owner", "name"}
    assert "owner=acme" in call and "name=widgets" in call
    assert any(a.startswith("query=query(") for a in call)


def test_fetch_pull_requests_all_digit_names_stay_strings(tmp_path, monkeypatch):
    # gh -F would send owner 2048 as a number and GitHub would reject it
    calls = install_fake_gh(
        tmp_path, monkeypatch, {"graphql:1234/2048": {"graphql_pages": [[]]}}
    )
    fetch_pull_requests("1234/2048")
    (call,) = calls()
    assert call[call.index("owner=1234") - 1] == "-f"
    assert call[call.index("name=2048") - 1] == "-f"


def test_fetch_pull_requests_state_mapping(tmp_path, monkeypatch):
    pages = [[node(state="OPEN"), node(state="CLOSED"), node(state="MERGED")]]
    install_fake_gh(tmp_path, monkeypatch, graphql_route(*pages))
    assert [pr["state"] for pr in fetch_pull_requests(REPO)] == [
        "open",
        "closed",
        "closed",
    ]


def test_fetch_pull_requests_collects_every_page(tmp_path, monkeypatch):
    pages = [[node(author=f"u{i}") for i in range(n, n + 2)] for n in (0, 2, 4)]
    install_fake_gh(tmp_path, monkeypatch, graphql_route(*pages))
    logins = [pr["login"] for pr in fetch_pull_requests(REPO)]
    assert logins == ["u0", "u1", "u2", "u3", "u4", "u5"]


def test_fetch_pull_requests_repository_without_pulls(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, graphql_route([]))
    assert fetch_pull_requests(REPO) == []


def test_fetch_pull_requests_error(tmp_path, monkeypatch):
    install_fake_gh(
        tmp_path,
        monkeypatch,
        {GRAPHQL: {"error": "gh: API rate limit exceeded (HTTP 403)\n"}},
    )
    with pytest.raises(GitHubError, match="rate limit"):
        fetch_pull_requests(REPO)


def test_fetch_pull_requests_error_without_stderr(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, {GRAPHQL: {"error": ""}})
    with pytest.raises(GitHubError, match="gh api graphql failed"):
        fetch_pull_requests(REPO)


def test_fetch_pull_requests_response_with_errors_key(tmp_path, monkeypatch):
    body = {"data": {"repository": None}, "errors": [{"message": "Could not resolve"}]}
    install_fake_gh(tmp_path, monkeypatch, {GRAPHQL: {"raw": json.dumps(body)}})
    with pytest.raises(GitHubError, match="Could not resolve"):
        fetch_pull_requests(REPO)


def test_fetch_pull_requests_errors_key_without_message(tmp_path, monkeypatch):
    body = {"errors": [{"type": "X"}]}
    install_fake_gh(tmp_path, monkeypatch, {GRAPHQL: {"raw": json.dumps(body)}})
    with pytest.raises(GitHubError, match="unknown error"):
        fetch_pull_requests(REPO)


def test_fetch_pull_requests_missing_repository(tmp_path, monkeypatch):
    body = {"data": {"repository": None}}
    install_fake_gh(tmp_path, monkeypatch, {GRAPHQL: {"raw": json.dumps(body)}})
    with pytest.raises(GitHubError, match="could not read pull requests"):
        fetch_pull_requests(REPO)


def test_fetch_pull_requests_invalid_json(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, {GRAPHQL: {"raw": "<html>oops"}})
    with pytest.raises(GitHubError, match="invalid JSON"):
        fetch_pull_requests(REPO)


def test_fetch_pull_requests_unknown_repository_is_404(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch)
    with pytest.raises(GitHubError, match="HTTP 404"):
        fetch_pull_requests(REPO)


# ─── count_pull_requests ─────────────────────────────────────────────────────

START, END = "03/01/2026", "03/31/2026"
D = datetime.datetime


def count_one(pr, start=START, end=END, branch=None):
    return count_pull_requests([pr], start, end, branch)["u"]


def counted(opened, merged, closed, self_merged):
    return {
        "prs_opened": opened,
        "prs_merged": merged,
        "prs_closed_unmerged": closed,
        "prs_self_merged": self_merged,
    }


def test_counts_from_fixture_prs(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, pulls_routes())
    prs = fetch_pull_requests(REPO)
    # created_at near month edges is irrelevant here: use a very wide range
    counts = count_pull_requests(prs, "01/01/2020", "12/31/2030")
    assert counts == {
        "alice-dev": counted(2, 2, 0, 1),
        "bob-codes": counted(2, 0, 1, 0),
        "ghost": counted(1, 0, 1, 0),
        "dependabot[bot]": counted(1, 1, 0, 1),
    }


def test_open_pr_is_only_opened():
    pr = make_pr(created=utc_z(D(2026, 3, 10, 12)))
    assert count_one(pr) == {
        "prs_opened": 1,
        "prs_merged": 0,
        "prs_closed_unmerged": 0,
        "prs_self_merged": 0,
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
        "prs_self_merged": 0,
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
        "prs_self_merged": 0,
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
        "prs_self_merged": 0,
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
        "prs_self_merged": 0,
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
    assert only_main == {"a": counted(1, 0, 0, 0)}
    assert count_pull_requests(prs, START, END, branch="nope") == {}


def test_ghost_and_bot_counted_like_others(tmp_path, monkeypatch):
    install_fake_gh(tmp_path, monkeypatch, pulls_routes())
    counts = count_pull_requests(fetch_pull_requests(REPO), "01/01/2020", "12/31/2030")
    assert counts["ghost"]["prs_opened"] == 1
    assert counts["dependabot[bot]"]["prs_merged"] == 1


# STAT-12


def self_merge(**fields):
    created = utc_z(D(2026, 3, 10, 12))
    merged = utc_z(D(2026, 3, 11, 12))
    return make_pr(created=created, merged=merged, closed=merged, **fields)


def test_self_merged_pr_counts_in_merged_too():
    row = count_one(self_merge(merged_by="u"))
    assert (row["prs_merged"], row["prs_self_merged"]) == (1, 1)


def test_pr_merged_by_someone_else_is_not_self_merged():
    row = count_one(self_merge(merged_by="other"))
    assert (row["prs_merged"], row["prs_self_merged"]) == (1, 0)


def test_self_merge_compares_logins_ignoring_case():
    row = count_pull_requests([self_merge(login="Ada", merged_by="aDA")], START, END)
    assert row["Ada"]["prs_self_merged"] == 1


def test_unknown_merger_is_not_self_merged():
    assert count_one(self_merge(merged_by=None))["prs_self_merged"] == 0


def test_self_merge_outside_the_range_is_not_counted():
    pr = self_merge(merged_by="u")
    assert count_one(pr, "04/01/2026", "04/30/2026")["prs_self_merged"] == 0


def test_self_merge_respects_the_branch_filter():
    prs = [
        self_merge(merged_by="u", base="dev"),
        self_merge(merged_by="other", base="main"),
    ]
    assert count_pull_requests(prs, START, END, "main")["u"] == counted(1, 1, 0, 0)
    assert count_pull_requests(prs, START, END, "dev")["u"] == counted(1, 1, 0, 1)
    assert count_pull_requests(prs, START, END)["u"] == counted(2, 2, 0, 1)


def test_unmerged_pr_is_never_self_merged():
    pr = make_pr(created=utc_z(D(2026, 3, 10, 12)), merged_by="u")
    assert count_one(pr)["prs_self_merged"] == 0


def test_pr_dict_without_merged_by_counts_as_not_self_merged():
    pr = self_merge()
    del pr["merged_by"]
    assert count_one(pr)["prs_self_merged"] == 0


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


# --- pushes and website commits (STAT-14, STAT-15)


def test_fetch_pushes_encodes_the_branch_and_keeps_only_pushes(monkeypatch):
    asked = []

    def fake_api(path, paginate=False):
        asked.append((path, paginate))
        return [
            {"activity_type": "push", "timestamp": "t1", "actor": {"login": "a"}},
            {"activity_type": "force_push", "timestamp": "t2", "actor": None},
            {"activity_type": "pr_merge", "timestamp": "t3", "actor": {"login": "b"}},
            {"activity_type": "branch_creation", "timestamp": "t4", "actor": None},
        ]

    monkeypatch.setattr(github, "gh_api", fake_api)
    pushes = github.fetch_pushes("o/r", "feat/a b#1&x")
    assert asked == [
        ("repos/o/r/activity?per_page=100&ref=refs/heads/feat/a%20b%231%26x", True)
    ]
    assert pushes == [
        {"login": "a", "timestamp": "t1"},
        {"login": "ghost", "timestamp": "t2"},
    ]


def test_count_pushes_uses_the_inclusive_range():
    pushes = [
        {"login": "a", "timestamp": "2024-06-01T12:00:00Z"},
        {"login": "a", "timestamp": "2020-01-01T12:00:00Z"},
        {"login": "b", "timestamp": "2024-06-02T12:00:00Z"},
        {"login": "c", "timestamp": None},
    ]
    assert github.count_pushes(pushes, "01/01/2024", "12/31/2024") == {"a": 1, "b": 1}


def test_count_web_commits_skips_other_committers_and_merge_results():
    # 1710235800 is 2024-03-12T09:30:00Z
    prs = [
        # squash merged: GitHub committed 10 seconds before the merge time
        {
            "merged_at": "2024-03-12T09:30:10Z",
            "merge_commit": "sq",
            "merge_committed_at": "2024-03-12T09:30:00Z",
        },
        # no merge commit known: compared by merge time
        {"merged_at": "2024-03-20T00:00:00Z"},
        {"merged_at": None, "merge_commit": None, "merge_committed_at": None},
    ]
    gh = "noreply@github.com"
    commits = [
        {"hash": "sq", "name": "A", "committer_email": gh, "committed": 1710235800},
        # another commit of a rebase merge: 2 seconds from the merge commit
        {"hash": "r2", "name": "A", "committer_email": gh, "committed": 1710235802},
        {"hash": "x1", "name": "A", "committer_email": gh, "committed": 1710235803},
        {"hash": "x2", "name": "A", "committer_email": gh, "committed": 1710235796},
        {
            "hash": "x3",
            "name": "A",
            "committer_email": " NoReply@GitHub.com ",
            "committed": 5,
        },
        {"hash": "x4", "name": "B", "committer_email": "b@example.com", "committed": 5},
        {"hash": "m", "name": "B", "committer_email": gh, "committed": 1710892800 - 1},
    ]
    # x1 and x2 are 3 and 4 seconds away; "m" is 1 second before the merge
    assert github.count_web_commits(commits, prs) == {"A": 3}


# ─── days (OUT-7) ────────────────────────────────────────────────────────────


def test_local_day_of_timestamp_and_epoch_seconds():
    late = datetime.datetime(2024, 3, 10, 23, 59, 59)
    early = datetime.datetime(2024, 3, 11, 0, 0, 0)
    assert local_day(utc_z(late)) == "03/10/2024"
    assert local_day(utc_z(early)) == "03/11/2024"
    assert local_day(time.mktime(late.timetuple())) == "03/10/2024"
    assert local_day(int(time.mktime(early.timetuple()))) == "03/11/2024"


def test_event_days_lists_every_pull_request_and_push_day_in_range():
    day = lambda d, h=12: utc_z(datetime.datetime(2024, 3, d, h))
    prs = [
        make_pr(created=day(1), merged=day(2), closed=day(2)),
        make_pr(created=day(3), closed=day(4)),
        make_pr(created=day(5)),
        make_pr(created=utc_z(datetime.datetime(2023, 12, 31, 23, 59, 59))),
    ]
    pushes = [{"login": "u", "timestamp": day(6)}, {"login": "u", "timestamp": day(31)}]
    assert event_days(prs, pushes, "01/01/2024", "03/30/2024") == {
        "03/01/2024",
        "03/02/2024",
        "03/03/2024",
        "03/04/2024",
        "03/05/2024",
        "03/06/2024",
    }
    assert event_days([], [], "01/01/2024", "03/30/2024") == set()
