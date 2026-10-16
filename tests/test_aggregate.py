"""Tests for combining rows by developer or by repository (OUT-6).

All names, emails and logins here are invented.
"""

import pytest

from gitlogstats.aggregate import (
    DAY,
    DEVELOPER,
    REPOSITORY,
    aggregate,
    developer_key,
    fieldnames,
    first_text,
    merge_emails,
    sum_values,
)
from gitlogstats.git_logs_parser import FIELDNAMES
from gitlogstats.github import (
    ACTIVITY_FIELDNAMES,
    EMAIL_FIELDNAMES,
    GITHUB_FIELDNAMES,
)

GIT_COUNTS = ["commits", "insertions", "deletions", "files", "merges"]
PR_COUNTS = GITHUB_FIELDNAMES[1:]


def git_row(username, repository, commits=1, insertions=0, deletions=0, files=0):
    """A row as GitLogsParser.parse() reports it."""
    return {
        "username": username,
        "repository": repository,
        "start_date": "01/01/2024",
        "end_date": "12/31/2024",
        "commits": commits,
        "insertions": insertions,
        "deletions": deletions,
        "files": files,
        "merges": 0,
    }


def github_row(username, repository, login="", git_email="", github_email="", **n):
    """A row with the GitHub columns, as --github reports it."""
    row = git_row(username, repository, commits=n.pop("commits", 1))
    row["github_username"] = login
    for field in PR_COUNTS:
        row[field] = n.pop(field, 0)
    row["git_email"] = git_email
    row["github_email"] = github_email
    row["pushes_to_default"] = n.pop("pushes_to_default", 0)
    row["web_commits"] = n.pop("web_commits", 0)
    assert not n
    return row


def unavailable(username, repository, git_email="", commits=1):
    """A --github row of a repository GitHub could not be asked about."""
    row = git_row(username, repository, commits=commits)
    for field in GITHUB_FIELDNAMES + EMAIL_FIELDNAMES + ACTIVITY_FIELDNAMES:
        row[field] = None
    row["git_email"] = git_email
    return row


class TestFieldnames:
    def test_developer_without_github(self):
        assert fieldnames(DEVELOPER, False) == [
            "username",
            "start_date",
            "end_date",
            *GIT_COUNTS,
            "repositories",
        ]

    def test_developer_with_github(self):
        assert fieldnames(DEVELOPER, True) == [
            "username",
            "start_date",
            "end_date",
            *GIT_COUNTS,
            "repositories",
            *GITHUB_FIELDNAMES,
            *EMAIL_FIELDNAMES,
            *ACTIVITY_FIELDNAMES,
        ]

    def test_repository_without_github(self):
        assert fieldnames(REPOSITORY, False) == [
            "repository",
            "start_date",
            "end_date",
            *GIT_COUNTS,
            "contributors",
        ]

    def test_repository_with_github_has_no_identity_columns(self):
        columns = fieldnames(REPOSITORY, True)
        assert columns == [
            "repository",
            "start_date",
            "end_date",
            *GIT_COUNTS,
            "contributors",
            *PR_COUNTS,
            *ACTIVITY_FIELDNAMES,
        ]
        assert not {"username", "github_username", *EMAIL_FIELDNAMES} & set(columns)

    def test_git_counts_match_the_parser_columns(self):
        assert GIT_COUNTS == FIELDNAMES[4:]


class TestHelpers:
    @pytest.mark.parametrize(
        "values, expected",
        [([1, 2, 3], 6), ([None, 2, None], 2), ([None, None], None), ([0], 0)],
    )
    def test_sum_values(self, values, expected):
        assert sum_values(values) == expected

    @pytest.mark.parametrize(
        "values, expected",
        [
            (["", "ada", "bob"], "ada"),
            ([None, "", None], ""),
            ([None, None], None),
            ([None, "ada"], "ada"),
        ],
    )
    def test_first_text(self, values, expected):
        assert first_text(iter(values)) == expected

    @pytest.mark.parametrize(
        "values, expected",
        [
            (
                ["b@x.example; a@x.example", "A@x.example", ""],
                "A@x.example; b@x.example",
            ),
            ([None, "c@x.example"], "c@x.example"),
            (["", None], ""),
            ([None, None], None),
        ],
    )
    def test_merge_emails(self, values, expected):
        assert merge_emails(iter(values)) == expected

    def test_developer_key(self):
        assert developer_key(git_row("Ada", "one")) == ("git", "Ada")
        assert developer_key(github_row("Ada", "one", login="AdaL")) == (
            "github",
            "adal",
        )
        assert developer_key(unavailable("Ada", "one")) == ("git", "Ada")


class TestByDeveloper:
    def test_sums_each_developer_over_repositories(self):
        rows = [
            git_row("bob", "one", commits=1, insertions=5, deletions=1, files=2),
            git_row("Ada", "one", commits=2, insertions=10, deletions=3, files=4),
            git_row("Ada", "two", commits=3, insertions=7, deletions=0, files=1),
        ]
        assert aggregate(rows, DEVELOPER, False) == [
            {
                "username": "Ada",
                "start_date": "01/01/2024",
                "end_date": "12/31/2024",
                "commits": 5,
                "insertions": 17,
                "deletions": 3,
                "files": 5,
                "merges": 0,
                "repositories": 2,
            },
            {
                "username": "bob",
                "start_date": "01/01/2024",
                "end_date": "12/31/2024",
                "commits": 1,
                "insertions": 5,
                "deletions": 1,
                "files": 2,
                "merges": 0,
                "repositories": 1,
            },
        ]

    def test_git_usernames_must_match_exactly(self):
        rows = [git_row("Ada", "one"), git_row("ada", "two")]
        assert [r["username"] for r in aggregate(rows, DEVELOPER, False)] == [
            "Ada",
            "ada",
        ]

    def test_same_repository_twice_counts_once_in_repositories(self):
        rows = [git_row("Ada", "one"), git_row("Ada", "one")]
        (row,) = aggregate(rows, DEVELOPER, False)
        assert (row["commits"], row["repositories"]) == (2, 1)

    def test_github_rows_combine_by_login_ignoring_case(self):
        rows = [
            github_row("ada", "one", login="AdaL", git_email="a@home.example"),
            github_row(
                "Ada Lovelace",
                "two",
                login="adal",
                commits=5,
                git_email="a@work.example",
                github_email="ada@pub.example",
                prs_opened=2,
                prs_merged=1,
                pushes_to_default=3,
                web_commits=1,
            ),
        ]
        (row,) = aggregate(rows, DEVELOPER, True)
        assert list(row) == fieldnames(DEVELOPER, True)
        assert row["username"] == "Ada Lovelace"  # the most commits
        assert row["github_username"] == "AdaL"
        assert row["git_email"] == "a@home.example; a@work.example"
        assert row["github_email"] == "ada@pub.example"
        assert (row["commits"], row["repositories"]) == (6, 2)
        assert [row[f] for f in PR_COUNTS] == [2, 1, 0, 0]
        assert (row["pushes_to_default"], row["web_commits"]) == (3, 1)

    @pytest.mark.parametrize("reverse", [False, True])
    def test_username_does_not_depend_on_repository_order(self, reverse):
        rows = [
            github_row("a.smith", "one", login="agh", commits=0),
            github_row("Alice Smith", "two", login="agh", commits=50),
            github_row("alice", "three", login="agh", commits=50),
        ]
        rows = rows[::-1] if reverse else rows
        (row,) = aggregate(rows, DEVELOPER, True)
        assert row["username"] == "Alice Smith"  # most commits, ties alphabetical

    def test_repositories_counts_only_active_rows(self):
        idle = git_row("Ada", "two", commits=0)
        rows = [git_row("Ada", "one"), idle, git_row("Bob", "two", commits=0)]
        ada, bob = aggregate(rows, DEVELOPER, False)
        assert (ada["repositories"], bob["repositories"]) == (1, 0)

    def test_github_activity_alone_makes_a_row_active(self):
        rows = [
            github_row("ada", "one", login="adal", commits=0, prs_opened=1),
            github_row("ada", "two", login="adal", commits=0, pushes_to_default=1),
            github_row("ada", "three", login="adal", commits=0),
            unavailable("ada", "four", commits=0),
        ]
        out = aggregate(rows, DEVELOPER, True)
        assert [(r["github_username"], r["repositories"]) for r in out] == [
            ("adal", 2),
            (None, 0),
        ]

    def test_github_only_row_takes_username_from_another_repository(self):
        rows = [
            github_row("", "one", login="adal", commits=0, prs_opened=1),
            github_row("ada", "two", login="adal"),
        ]
        (row,) = aggregate(rows, DEVELOPER, True)
        assert (row["username"], row["prs_opened"], row["commits"]) == ("ada", 1, 1)

    def test_github_only_developer_sorts_by_login(self):
        rows = [
            github_row("zed", "one"),
            github_row("", "one", login="Mia", commits=0, prs_opened=1),
            github_row("ada", "one"),
        ]
        names = [
            (r["username"], r["github_username"])
            for r in aggregate(rows, DEVELOPER, True)
        ]
        assert names == [("ada", ""), ("", "Mia"), ("zed", "")]

    def test_unavailable_counts_do_not_blank_the_total(self):
        rows = [
            github_row("bob", "one", git_email="b@x.example", prs_opened=2),
            unavailable("bob", "two", git_email="b@y.example"),
        ]
        (row,) = aggregate(rows, DEVELOPER, True)
        assert row["prs_opened"] == 2
        assert row["github_username"] == ""
        assert row["git_email"] == "b@x.example; b@y.example"
        assert row["github_email"] == ""

    def test_only_unavailable_rows_stay_unavailable(self):
        rows = [unavailable("bob", "one"), unavailable("bob", "two")]
        (row,) = aggregate(rows, DEVELOPER, True)
        assert row["commits"] == 2
        assert all(row[f] is None for f in GITHUB_FIELDNAMES + ACTIVITY_FIELDNAMES)
        assert row["github_email"] is None

    def test_matched_and_unmatched_rows_stay_apart(self):
        rows = [
            github_row("ada", "one", login="adal"),
            unavailable("ada", "two"),
        ]
        out = aggregate(rows, DEVELOPER, True)
        assert [(r["username"], r["github_username"]) for r in out] == [
            ("ada", "adal"),
            ("ada", None),
        ]


class TestByRepository:
    def test_sums_each_repository_over_contributors(self):
        rows = [
            git_row("Ada", "two", commits=3, insertions=7, files=1),
            git_row("Ada", "One", commits=2, insertions=10, deletions=3, files=4),
            git_row("bob", "One", commits=1, insertions=5, deletions=1, files=2),
        ]
        out = aggregate(rows, REPOSITORY, False)
        assert out == [
            {
                "repository": "One",
                "start_date": "01/01/2024",
                "end_date": "12/31/2024",
                "commits": 3,
                "insertions": 15,
                "deletions": 4,
                "files": 6,
                "merges": 0,
                "contributors": 2,
            },
            {
                "repository": "two",
                "start_date": "01/01/2024",
                "end_date": "12/31/2024",
                "commits": 3,
                "insertions": 7,
                "deletions": 0,
                "files": 1,
                "merges": 0,
                "contributors": 1,
            },
        ]

    def test_contributors_counts_only_active_rows(self):
        rows = [
            git_row("Ada", "one"),
            git_row("Bob", "one", commits=0),
            git_row("Cy", "two", commits=0),
        ]
        one, two = aggregate(rows, REPOSITORY, False)
        assert (one["contributors"], two["contributors"]) == (1, 0)

    def test_github_columns(self):
        rows = [
            github_row("ada", "one", login="adal", prs_opened=2, web_commits=1),
            github_row("", "one", login="mia", commits=0, prs_merged=1),
            unavailable("bob", "two"),
        ]
        one, two = aggregate(rows, REPOSITORY, True)
        assert list(one) == fieldnames(REPOSITORY, True)
        assert (one["contributors"], one["commits"]) == (2, 1)
        assert [one[f] for f in PR_COUNTS] == [2, 1, 0, 0]
        assert (one["pushes_to_default"], one["web_commits"]) == (0, 1)
        assert two["contributors"] == 1
        assert all(two[f] is None for f in PR_COUNTS + ACTIVITY_FIELDNAMES)


def day_row(row, date):
    """A row for a single day (OUT-7)."""
    return dict(row, date=date)


class TestByDay:
    def test_fieldnames(self):
        assert fieldnames(DAY, False) == [
            "date",
            *GIT_COUNTS,
            "repositories",
            "contributors",
        ]
        assert fieldnames(DAY, True) == fieldnames(DAY, False) + [
            *PR_COUNTS,
            *ACTIVITY_FIELDNAMES,
        ]

    def test_sums_each_day_in_date_order(self):
        rows = [
            day_row(git_row("Ada", "one", commits=2, insertions=3), "01/02/2025"),
            day_row(git_row("Ada", "one", commits=1, files=1), "12/31/2024"),
            day_row(git_row("Bob", "two", commits=1, deletions=4), "12/31/2024"),
            day_row(git_row("Ada", "two", commits=1, insertions=5), "12/31/2024"),
        ]
        out = aggregate(rows, DAY, False)
        assert out == [
            {
                "date": "12/31/2024",
                "commits": 3,
                "insertions": 5,
                "deletions": 4,
                "files": 1,
                "merges": 0,
                "repositories": 2,
                "contributors": 2,  # Ada counts once over two repositories
            },
            {
                "date": "01/02/2025",
                "commits": 2,
                "insertions": 3,
                "deletions": 0,
                "files": 0,
                "merges": 0,
                "repositories": 1,
                "contributors": 1,
            },
        ]

    def test_inactive_rows_and_days_are_left_out(self):
        rows = [
            day_row(git_row("Ada", "one"), "03/01/2024"),
            day_row(git_row("Bob", "two", commits=0), "03/01/2024"),
            day_row(git_row("Bob", "two", commits=0), "03/02/2024"),
        ]
        (row,) = aggregate(rows, DAY, False)
        assert (row["date"], row["repositories"], row["contributors"]) == (
            "03/01/2024",
            1,
            1,
        )

    def test_github_counts_and_one_person_under_two_logins_cases(self):
        rows = [
            day_row(github_row("ada", "one", login="AdaL", prs_opened=1), "03/01/2024"),
            day_row(
                github_row("", "two", login="adal", commits=0, pushes_to_default=2),
                "03/01/2024",
            ),
            day_row(
                github_row("", "two", login="mia", commits=0, prs_merged=1),
                "03/01/2024",
            ),
            day_row(unavailable("bob", "three"), "03/01/2024"),
            day_row(unavailable("bob", "three"), "03/02/2024"),
        ]
        first, second = aggregate(rows, DAY, True)
        assert list(first) == fieldnames(DAY, True)
        assert (first["repositories"], first["contributors"]) == (3, 3)
        assert (first["prs_opened"], first["prs_merged"]) == (1, 1)
        assert (first["pushes_to_default"], first["commits"]) == (2, 2)
        # only a repository GitHub could not be asked about was active that day
        assert second["commits"] == 1
        assert all(second[f] is None for f in PR_COUNTS + ACTIVITY_FIELDNAMES)


@pytest.mark.parametrize("mode", [DEVELOPER, REPOSITORY, DAY])
def test_no_rows(mode):
    assert aggregate([], mode, True) == []
