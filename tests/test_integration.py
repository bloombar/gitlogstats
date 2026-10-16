"""
Integration tests: build real git repositories and check the statistics that
GitLogsParser and the gitlogstats command derive from them.
"""

import csv
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from fake_gh import install_fake_gh
from gitlogstats import GitLogsParser
from gitlogstats.__main__ import main


# ─── Helpers ─────────────────────────────────────────────────────────────────


class Repo:
    """A throwaway git repository in which commits can be made by any author on any date."""

    def __init__(self, path):
        self.path = str(path)
        os.makedirs(self.path, exist_ok=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args, env=None):
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def write(self, name, content, mode="w"):
        full = os.path.join(self.path, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, mode) as f:
            f.write(content)

    @staticmethod
    def identity(author, date, email=None, committer=None):
        """Environment for a git command run as *author* (and *committer*) on *date*."""
        email = email or f"{author.split()[0].lower()}@example.com"
        committer_name, committer_email = committer or (author, email)
        return dict(
            os.environ,
            GIT_AUTHOR_NAME=author,
            GIT_AUTHOR_EMAIL=email,
            GIT_COMMITTER_NAME=committer_name,
            GIT_COMMITTER_EMAIL=committer_email,
            GIT_AUTHOR_DATE=date,
            GIT_COMMITTER_DATE=date,
        )

    def commit(
        self,
        author,
        message,
        date="2024-03-10 12:00:00",
        email=None,
        extra=(),
        committer=None,
    ):
        """Stage everything and commit it as *author* on *date* (local time)."""
        env = self.identity(author, date, email, committer)
        self.git("add", "-A")
        self.git(
            "commit",
            "-q",
            "--allow-empty",
            "--allow-empty-message",
            "-m",
            message,
            *extra,
            env=env,
        )

    def merge(
        self,
        author,
        *branches,
        message="Merge",
        date="2024-03-10 12:00:00",
        email=None,
        committer=None,
        options=("--no-ff",),
    ):
        """Merge *branches* into the current branch as *author* on *date*."""
        env = self.identity(author, date, email, committer)
        self.git("merge", "-q", *options, "-m", message, *branches, env=env)

    def branch(self, name, start=None):
        """Create and switch to a new branch."""
        self.git("checkout", "-q", "-b", name, *([start] if start else []))

    def switch(self, name):
        self.git("checkout", "-q", name)


def lines(n, prefix="line"):
    return "".join(f"{prefix} {i}\n" for i in range(n))


def stats(repo, monkeypatch, **kwargs):
    """Run the parser over *repo* and return its entries keyed by username."""
    monkeypatch.chdir(repo.path)  # the parser chdirs; this restores cwd afterwards
    options = dict(start="01/01/2024", end="12/31/2024", username=None)
    options.update(kwargs)
    parser = GitLogsParser(repo=repo.path, **options)
    return {e["username"]: e for e in parser.parse()}


def counts(entry):
    return (entry["commits"], entry["files"], entry["insertions"], entry["deletions"])


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path / "project")


# ─── Commit messages ─────────────────────────────────────────────────────────


class TestCommitMessages:
    def test_single_line_messages(self, repo, monkeypatch):
        repo.write("a.txt", lines(3))
        repo.commit("Alice", "Add a")
        repo.write("b.txt", lines(4))
        repo.commit("Alice", "Add b")
        assert counts(stats(repo, monkeypatch)["Alice"]) == (2, 2, 7, 0)

    def test_multi_line_messages(self, repo, monkeypatch):
        repo.write("a.txt", lines(3))
        repo.commit(
            "Alice", "Subject\n\nFirst paragraph\nwraps here.\n\n- bullet\n- bullet"
        )
        repo.write("b.txt", lines(4))
        repo.commit("Alice", "Subject\nimmediately followed by body, no blank line")
        assert counts(stats(repo, monkeypatch)["Alice"]) == (2, 2, 7, 0)

    def test_mixed_single_and_multi_line_messages(self, repo, monkeypatch):
        repo.write("a.txt", lines(1))
        repo.commit("Alice", "one")
        repo.write("b.txt", lines(2))
        repo.commit("Alice", "two\n\nwith a body")
        repo.write("c.txt", lines(3))
        repo.commit("Alice", "three")
        assert counts(stats(repo, monkeypatch)["Alice"]) == (3, 3, 6, 0)

    def test_messages_that_look_like_git_log_output(self, repo, monkeypatch):
        # text an old regex-based parser would have mistaken for log structure
        repo.write("a.txt", lines(2))
        repo.commit(
            "Alice",
            "Revert commit abc123\n\ncommit deadbeef\nAuthor: Mallory <m@example.com>\n"
            "Date: today\n\n 99 files changed, 999 insertions(+), 999 deletions(-)",
        )
        result = stats(repo, monkeypatch)
        assert counts(result["Alice"]) == (1, 1, 2, 0)
        assert "Mallory" not in result

    def test_empty_message(self, repo, monkeypatch):
        repo.write("a.txt", lines(5))
        repo.commit("Alice", "")
        assert counts(stats(repo, monkeypatch)["Alice"]) == (1, 1, 5, 0)

    def test_unicode_message_and_author(self, repo, monkeypatch):
        repo.write("a.txt", "héllo\n")
        repo.commit("Zoë Ångström", "Añadir 🎉\n\n日本語の本文")
        assert counts(stats(repo, monkeypatch)["Zoë Ångström"]) == (1, 1, 1, 0)


# ─── Kinds of change ─────────────────────────────────────────────────────────


class TestKindsOfChange:
    def test_modifications_count_insertions_and_deletions(self, repo, monkeypatch):
        repo.write("a.txt", lines(5))
        repo.commit("Alice", "add", date="2023-06-01 12:00:00")  # outside the range
        repo.write("a.txt", lines(3) + "changed\n")
        repo.commit("Bob", "edit")
        assert counts(stats(repo, monkeypatch)["Bob"]) == (1, 1, 1, 2)

    def test_deletion_only(self, repo, monkeypatch):
        repo.write("a.txt", lines(5))
        repo.commit("Alice", "add", date="2023-06-01 12:00:00")
        os.remove(os.path.join(repo.path, "a.txt"))
        repo.commit("Bob", "remove")
        assert counts(stats(repo, monkeypatch)["Bob"]) == (1, 1, 0, 5)

    def test_binary_file_counts_as_file_without_lines(self, repo, monkeypatch):
        repo.write("blob.bin", "\x00\x01\x02binary", mode="w")
        repo.commit("Alice", "binary")
        assert counts(stats(repo, monkeypatch)["Alice"]) == (1, 1, 0, 0)

    def test_pure_rename(self, repo, monkeypatch):
        repo.write("a.txt", lines(5))
        repo.commit("Alice", "add", date="2023-06-01 12:00:00")
        repo.git("mv", "a.txt", "b.txt")
        repo.commit("Bob", "rename")
        bob = stats(repo, monkeypatch)["Bob"]
        assert bob["commits"] == 1 and bob["insertions"] == 0 and bob["deletions"] == 0

    def test_files_in_subdirectories(self, repo, monkeypatch):
        repo.write("src/a.py", lines(2))
        repo.write("src/pkg/b.py", lines(3))
        repo.commit("Alice", "nested")
        assert counts(stats(repo, monkeypatch)["Alice"]) == (1, 2, 5, 0)

    def test_merge_commit_counted_as_merge_without_duplicating_stats(
        self, repo, monkeypatch
    ):
        repo.write("base.txt", lines(1))
        repo.commit("Alice", "base")
        repo.git("checkout", "-q", "-b", "feature")
        repo.write("feature.txt", lines(4))
        repo.commit("Bob", "feature work\n\nmulti-line")
        repo.git("checkout", "-q", "main")
        repo.write("main.txt", lines(2))
        repo.commit("Alice", "main work")
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Alice",
            GIT_AUTHOR_EMAIL="alice@example.com",
            GIT_COMMITTER_NAME="Alice",
            GIT_COMMITTER_EMAIL="alice@example.com",
            GIT_AUTHOR_DATE="2024-03-11 12:00:00",
            GIT_COMMITTER_DATE="2024-03-11 12:00:00",
        )
        repo.git(
            "merge",
            "-q",
            "--no-ff",
            "-m",
            "Merge feature\n\ninto main",
            "feature",
            env=env,
        )
        result = stats(repo, monkeypatch)
        # base + main work; the merge is counted only as a merge
        assert counts(result["Alice"]) == (2, 2, 3, 0)
        assert result["Alice"]["merges"] == 1
        assert counts(result["Bob"]) == (1, 1, 4, 0)
        assert result["Bob"]["merges"] == 0

    def test_empty_commit_is_ignored(self, repo, monkeypatch):
        repo.write("a.txt", lines(1))
        repo.commit("Alice", "real")
        repo.commit("Alice", "empty")  # --allow-empty: touches no paths
        assert counts(stats(repo, monkeypatch)["Alice"]) == (1, 1, 1, 0)


# ─── Authors ─────────────────────────────────────────────────────────────────


class TestAuthors:
    @pytest.fixture
    def team(self, repo):
        repo.write("al.txt", lines(1))
        repo.commit("Al", "al", email="al@example.com")
        repo.write("alice.txt", lines(2))
        repo.commit("Alice", "alice", email="alice@example.com")
        repo.write("mary.txt", lines(3))
        repo.commit("Mary O'Neil (C++) [TA]", 'quote "this"', email="mary@example.com")
        repo.write("dot.txt", lines(4))
        repo.commit("A.l", "regex-looking name", email="dot@example.com")
        return repo

    def test_each_author_is_counted_separately(self, team, monkeypatch):
        result = stats(team, monkeypatch)
        assert counts(result["Al"]) == (1, 1, 1, 0)
        assert counts(result["Alice"]) == (1, 1, 2, 0)
        assert counts(result["Mary O'Neil (C++) [TA]"]) == (1, 1, 3, 0)
        assert counts(result["A.l"]) == (1, 1, 4, 0)

    def test_totals_match_repository_totals(self, team, monkeypatch):
        result = stats(team, monkeypatch)
        assert sum(e["commits"] for e in result.values()) == 4
        assert sum(e["insertions"] for e in result.values()) == 10

    @pytest.mark.parametrize(
        "user,expected",
        [
            ("Al", (1, 1, 1, 0)),
            ("Alice", (1, 1, 2, 0)),
            ("Mary O'Neil (C++) [TA]", (1, 1, 3, 0)),
            ("alice@example.com", (1, 1, 2, 0)),
            ("Nobody", (0, 0, 0, 0)),
        ],
    )
    def test_username_option(self, team, monkeypatch, user, expected):
        result = stats(team, monkeypatch, username=user)
        assert list(result) == [user]
        assert counts(result[user]) == expected

    def test_mailmap_merges_identities(self, repo, monkeypatch):
        repo.write("a.txt", lines(1))
        repo.commit("alice-laptop", "a", email="alice@laptop")
        repo.write(".mailmap", "Alice <alice@example.com> <alice@laptop>\n")
        repo.commit("Alice", "b", email="alice@example.com")
        result = stats(repo, monkeypatch)
        assert list(result) == ["Alice"]
        assert result["Alice"]["commits"] == 2


# ─── Date range ──────────────────────────────────────────────────────────────


class TestDateRange:
    @pytest.fixture
    def dated(self, repo):
        for i, date in enumerate(
            [
                "2024-02-29 23:59:59",  # the day before: excluded
                "2024-03-01 00:00:01",  # first second of the start date: included
                "2024-03-15 12:00:00",  # middle: included
                "2024-03-31 23:59:58",  # last second of the end date: included
                "2024-04-01 00:00:01",  # the day after: excluded
            ]
        ):
            repo.write(f"f{i}.txt", lines(i + 1))
            repo.commit("Alice", f"commit {i}", date=date)
        return repo

    def test_range_is_inclusive_of_whole_start_and_end_days(self, dated, monkeypatch):
        alice = stats(dated, monkeypatch, start="03/01/2024", end="03/31/2024")["Alice"]
        assert counts(alice) == (3, 3, 2 + 3 + 4, 0)

    def test_single_day_range(self, dated, monkeypatch):
        alice = stats(dated, monkeypatch, start="03/15/2024", end="03/15/2024")["Alice"]
        assert counts(alice) == (1, 1, 3, 0)

    def test_contributor_outside_range_reported_with_zeros_unless_clean(
        self, dated, monkeypatch
    ):
        dated.write("bob.txt", lines(1))
        dated.commit("Bob", "old", date="2020-01-01 12:00:00")
        result = stats(dated, monkeypatch, start="03/01/2024", end="03/31/2024")
        assert counts(result["Bob"]) == (0, 0, 0, 0)
        result = stats(
            dated, monkeypatch, start="03/01/2024", end="03/31/2024", clean=True
        )
        assert "Bob" not in result


# ─── Exclusions ──────────────────────────────────────────────────────────────


class TestExclusions:
    def test_excluded_files_are_not_counted_anywhere_in_tree(self, repo, monkeypatch):
        repo.write("code.py", lines(2))
        repo.write("data.json", lines(50))
        repo.write("sub/dir/more.json", lines(50))
        repo.write("package-lock.json", lines(50))
        repo.commit("Alice", "mixed")
        alice = stats(repo, monkeypatch, exclusions=["*.json"])["Alice"]
        assert counts(alice) == (1, 1, 2, 0)

    def test_commit_touching_only_excluded_files_is_not_counted(
        self, repo, monkeypatch
    ):
        repo.write("code.py", lines(2))
        repo.commit("Alice", "code")
        repo.write("image.jpg", lines(10))
        repo.commit("Alice", "image only")
        alice = stats(repo, monkeypatch, exclusions=["*.jpg"])["Alice"]
        assert counts(alice) == (1, 1, 2, 0)

    def test_exact_filename_exclusion(self, repo, monkeypatch):
        repo.write("Pipfile.lock", lines(10))
        repo.write("lib/Pipfile.lock", lines(10))
        repo.write("keep.lock", lines(1))
        repo.commit("Alice", "locks")
        alice = stats(repo, monkeypatch, exclusions=["Pipfile.lock"])["Alice"]
        assert counts(alice) == (1, 1, 1, 0)


# ─── Command line ────────────────────────────────────────────────────────────


class TestCommandLine:
    @pytest.fixture
    def remotes(self, tmp_path):
        """Two 'remote' repositories that the command clones by path."""
        one = Repo(tmp_path / "remotes" / "one")
        one.write("a.txt", lines(3))
        one.commit("Alice", "one: add\n\nmulti-line body")
        one.write("b.txt", lines(1))
        one.commit("Bob", "one: bob")
        two = Repo(tmp_path / "remotes" / "two.repo")
        two.write("c.txt", lines(2))
        two.commit("Alice", "two: add")
        return one, two

    def run(self, monkeypatch, capsys, cwd, *argv):
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(sys, "argv", ["gitlogstats", *argv])
        main()
        return capsys.readouterr().out

    def dates(self):
        return ["-s", "01/01/2024", "-e", "12/31/2024"]

    def test_single_repository_csv(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(
            monkeypatch, capsys, tmp_path, "-r", remotes[0].path, *self.dates()
        )
        rows = [l for l in out.splitlines() if l]
        assert (
            rows[0]
            == "username,repository,start_date,end_date,commits,insertions,deletions,files,merges"
        )
        assert "Alice,one,01/01/2024,12/31/2024,1,3,0,1,0" in rows
        assert "Bob,one,01/01/2024,12/31/2024,1,1,0,1,0" in rows

    def test_repofile_json_is_one_array(self, remotes, tmp_path, monkeypatch, capsys):
        repofile = tmp_path / "repos.txt"
        repofile.write_text(f"# test repos\n{remotes[0].path}\n\n{remotes[1].path}\n\n")
        out = self.run(
            monkeypatch,
            capsys,
            tmp_path,
            "-rf",
            str(repofile),
            "-f",
            "json",
            *self.dates(),
        )
        parsed = json.loads(out)
        assert {(e["repository"], e["username"], e["commits"]) for e in parsed} == {
            ("one", "Alice", 1),
            ("one", "Bob", 1),
            ("two.repo", "Alice", 1),
        }

    def test_repofile_csv_has_a_single_header(
        self, remotes, tmp_path, monkeypatch, capsys
    ):
        repofile = tmp_path / "repos.txt"
        repofile.write_text(f"{remotes[0].path}\n{remotes[1].path}\n")
        out = self.run(
            monkeypatch, capsys, tmp_path, "-rf", str(repofile), *self.dates()
        )
        rows = [l for l in out.splitlines() if l]
        assert len(rows) == 4
        assert sum(r.startswith("username,") for r in rows) == 1

    def test_markdown_and_user_filter(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(
            monkeypatch,
            capsys,
            tmp_path,
            "-r",
            remotes[0].path,
            "-u",
            "Bob",
            "-f",
            "markdown",
            *self.dates(),
        )
        rows = [l for l in out.splitlines() if l]
        assert len(rows) == 3 and "| Bob | one |" in rows[2]

    def test_zero_activity_contributors_kept_by_default_and_removed_with_clean(
        self, remotes, tmp_path, monkeypatch, capsys
    ):
        argv = ["-r", remotes[0].path, "-s", "01/01/2024", "-e", "01/31/2024"]
        out = self.run(monkeypatch, capsys, tmp_path, *argv)
        assert (
            len([l for l in out.splitlines() if l]) == 3
        )  # header + Alice + Bob, zeros
        out = self.run(monkeypatch, capsys, tmp_path, *argv, "-c")
        assert out == ",".join(TestOutputFormat.FIELDS) + "\n"  # header only

    def test_rerun_pulls_new_commits(self, remotes, tmp_path, monkeypatch, capsys):
        argv = ["-r", remotes[0].path, "-u", "Alice", "-f", "json", *self.dates()]
        assert (
            json.loads(self.run(monkeypatch, capsys, tmp_path, *argv))[0]["commits"]
            == 1
        )
        remotes[0].write("new.txt", lines(1))
        remotes[0].commit("Alice", "later")
        assert (
            json.loads(self.run(monkeypatch, capsys, tmp_path, *argv))[0]["commits"]
            == 2
        )

    def test_branch_option_and_return_to_default_branch(
        self, remotes, tmp_path, monkeypatch, capsys
    ):
        one = remotes[0]
        one.git("checkout", "-q", "-b", "dev")
        one.write("dev.txt", lines(7))
        one.commit("Alice", "dev only")
        one.git("checkout", "-q", "main")
        base = ["-r", one.path, "-u", "Alice", "-f", "json", *self.dates()]
        on_dev = json.loads(self.run(monkeypatch, capsys, tmp_path, *base, "-b", "dev"))
        assert on_dev[0]["commits"] == 2
        on_main = json.loads(self.run(monkeypatch, capsys, tmp_path, *base))
        assert on_main[0]["commits"] == 1

    def test_custom_exclusions(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(
            monkeypatch,
            capsys,
            tmp_path,
            "-r",
            remotes[0].path,
            "-u",
            "Alice",
            "-x",
            "a.txt, ,*.md",
            "-f",
            "json",
            *self.dates(),
        )
        assert json.loads(out)[0]["commits"] == 0

    @pytest.mark.parametrize(
        "argv",
        [
            ["-s", "2024-01-01"],
            ["-e", "13/45/2024"],
            ["-s", "02/01/2024", "-e", "01/01/2024"],
        ],
    )
    def test_invalid_dates_are_rejected(
        self, remotes, tmp_path, monkeypatch, capsys, argv
    ):
        with pytest.raises(SystemExit) as exc:
            self.run(monkeypatch, capsys, tmp_path, "-r", remotes[0].path, *argv)
        assert exc.value.code == 2


# ─── Output format: exact CSV and JSON for single and multiple repositories ──


class TestOutputFormat:
    FIELDS = [
        "username",
        "repository",
        "start_date",
        "end_date",
        "commits",
        "insertions",
        "deletions",
        "files",
        "merges",
    ]

    @pytest.fixture
    def remotes(self, tmp_path):
        """Two repositories with author names that need quoting or escaping."""
        one = Repo(tmp_path / "remotes" / "alpha")
        one.write("a.txt", lines(3))
        one.commit("Smith, Jo", "subject\n\nbody", email="jo@example.com")
        one.write("b.txt", lines(2))
        one.commit('Dana "DJ" Jones', "one line", email="dj@example.com")
        two = Repo(tmp_path / "remotes" / "beta.repo")
        two.write("c.txt", lines(4))
        two.commit("Smith, Jo", "", email="jo@example.com")
        repofile = tmp_path / "repos.txt"
        repofile.write_text(f"{one.path}\n{two.path}\n")
        return one, two, repofile

    def run(self, monkeypatch, capsys, cwd, *argv):
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(
            sys, "argv", ["gitlogstats", "-s", "01/01/2024", "-e", "12/31/2024", *argv]
        )
        main()
        return capsys.readouterr().out

    def test_single_repository_csv(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(monkeypatch, capsys, tmp_path, "-r", remotes[0].path)
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,files,merges\n"
            '"Dana ""DJ"" Jones",alpha,01/01/2024,12/31/2024,1,2,0,1,0\n'
            '"Smith, Jo",alpha,01/01/2024,12/31/2024,1,3,0,1,0\n'
        )

    def test_multiple_repositories_csv(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(monkeypatch, capsys, tmp_path, "-rf", str(remotes[2]))
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,files,merges\n"
            '"Dana ""DJ"" Jones",alpha,01/01/2024,12/31/2024,1,2,0,1,0\n'
            '"Smith, Jo",alpha,01/01/2024,12/31/2024,1,3,0,1,0\n'
            '"Smith, Jo",beta.repo,01/01/2024,12/31/2024,1,4,0,1,0\n'
        )

    def test_empty_csv_is_header_only(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(
            monkeypatch, capsys, tmp_path, "-rf", str(remotes[2]), "-u", "X", "-c"
        )
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,files,merges\n"
        )

    @pytest.mark.parametrize("multi", [False, True])
    def test_json(self, remotes, tmp_path, monkeypatch, capsys, multi):
        source = ["-rf", str(remotes[2])] if multi else ["-r", remotes[0].path]
        out = self.run(monkeypatch, capsys, tmp_path, *source, "-f", "json", "-v")
        assert out.endswith("]\n") and out.count("\n") == 1  # one array, nothing else
        data = json.loads(out)
        assert all(list(d) == self.FIELDS for d in data)
        assert all(type(d[k]) is int for d in data for k in self.FIELDS[4:])
        assert [(d["username"], d["repository"], d["insertions"]) for d in data] == [
            ('Dana "DJ" Jones', "alpha", 2),
            ("Smith, Jo", "alpha", 3),
        ] + ([("Smith, Jo", "beta.repo", 4)] if multi else [])

    def test_empty_json_is_empty_array(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(
            monkeypatch,
            capsys,
            tmp_path,
            "-rf",
            str(remotes[2]),
            "-u",
            "X",
            "-c",
            "-f",
            "json",
        )
        assert out == "[]\n"


# ─── Merges ──────────────────────────────────────────────────────────────────


def feature(repo, name, author, files, start=None):
    """Make a branch *name* with one commit by *author* adding *files* ({path: lines}), then return to main."""
    repo.branch(name, start)
    for path, n in files.items():
        repo.write(path, lines(n, name))
    repo.commit(author, f"{name} work")
    repo.switch("main")


@pytest.fixture
def base(repo):
    repo.write("base.txt", lines(1))
    repo.commit("Alice", "base")
    return repo


class TestMerges:
    def test_local_no_ff_merge_counted_for_its_author(self, base, monkeypatch):
        feature(base, "f", "Bob", {"f.txt": 3})
        base.merge("Carol", "f", message="Merge branch 'f'\n\nwith a body")
        result = stats(base, monkeypatch)
        assert result["Carol"]["merges"] == 1
        assert counts(result["Carol"]) == (0, 0, 0, 0)  # merges are not commits
        assert result["Bob"]["merges"] == 0 and counts(result["Bob"]) == (1, 1, 3, 0)

    def test_merge_when_main_did_not_move(self, base, monkeypatch):
        # regression: git's history simplification used to hide this merge
        feature(base, "f", "Bob", {"f.txt": 3})
        base.merge("Carol", "f")
        assert stats(base, monkeypatch)["Carol"]["merges"] == 1

    def test_merge_when_both_sides_moved(self, base, monkeypatch):
        feature(base, "f", "Bob", {"f.txt": 3})
        base.write("main.txt", lines(1))
        base.commit("Alice", "main work")
        base.merge("Carol", "f")
        assert stats(base, monkeypatch)["Carol"]["merges"] == 1

    def test_merge_on_github_credited_to_the_person_who_merged(self, base, monkeypatch):
        # a pull request merged in the GitHub web interface: the author is the
        # person who clicked Merge, the committer is GitHub itself
        feature(base, "f", "Bob", {"f.txt": 3})
        base.merge(
            "Carol",
            "f",
            message="Merge pull request #1 from team/f",
            committer=("GitHub", "noreply@github.com"),
        )
        result = stats(base, monkeypatch)
        assert result["Carol"]["merges"] == 1
        assert "GitHub" not in result

    def test_several_merges_by_several_people(self, base, monkeypatch):
        for i, merger in enumerate(["Carol", "Carol", "Dan"]):
            feature(base, f"f{i}", "Bob", {f"f{i}.txt": 1})
            base.merge(merger, f"f{i}")
        result = stats(base, monkeypatch)
        assert (result["Carol"]["merges"], result["Dan"]["merges"]) == (2, 1)
        assert result["Bob"]["commits"] == 3

    def test_octopus_merge_counted_once(self, base, monkeypatch):
        feature(base, "a", "Bob", {"a.txt": 1})
        feature(base, "b", "Bob", {"b.txt": 1})
        base.merge("Carol", "a", "b", options=())
        assert stats(base, monkeypatch)["Carol"]["merges"] == 1

    def test_merge_of_conflicting_branches(self, base, monkeypatch):
        feature(base, "f", "Bob", {"shared.txt": 2})
        base.write("shared.txt", lines(3, "main"))
        base.commit("Alice", "main side")
        with pytest.raises(subprocess.CalledProcessError):
            base.merge("Carol", "f")
        base.write("shared.txt", lines(1, "resolved"))
        base.git("add", "-A")
        env = Repo.identity("Carol", "2024-03-10 12:00:00")
        base.git("commit", "-q", "--no-edit", env=env)
        result = stats(base, monkeypatch)
        assert result["Carol"]["merges"] == 1
        assert counts(result["Carol"]) == (0, 0, 0, 0)

    def test_sync_merge_inside_feature_branch_not_counted(self, base, monkeypatch):
        # e.g. `git pull` or GitHub's "Update branch": main merged into a feature
        base.branch("f")
        base.write("f.txt", lines(2))
        base.commit("Bob", "f work")
        base.switch("main")
        base.write("main.txt", lines(1))
        base.commit("Alice", "main work")
        base.switch("f")
        base.merge("Bob", "main", message="Merge branch 'main' into f")
        base.switch("main")
        base.merge("Carol", "f")
        result = stats(base, monkeypatch)
        assert result["Bob"]["merges"] == 0
        assert result["Carol"]["merges"] == 1

    def test_fast_forward_merge_not_counted(self, base, monkeypatch):
        feature(base, "f", "Bob", {"f.txt": 3})
        base.merge("Carol", "f", options=("--ff-only",))
        result = stats(base, monkeypatch)
        # no merge commit exists, so the person who merged leaves no trace
        assert "Carol" not in result
        assert all(e["merges"] == 0 for e in result.values())
        assert counts(result["Bob"]) == (1, 1, 3, 0)

    def test_squash_merge_not_counted(self, base, monkeypatch):
        feature(base, "f", "Bob", {"f.txt": 3})
        base.git("merge", "-q", "--squash", "f")
        base.commit("Carol", "Squashed f")
        result = stats(base, monkeypatch)
        # the squash commit is an ordinary commit by the person who made it,
        # and the branch's own commits never reach main
        assert all(e["merges"] == 0 for e in result.values())
        assert counts(result["Carol"]) == (1, 1, 3, 0)
        assert "Bob" not in result

    def test_rebase_merge_not_counted(self, base, monkeypatch):
        feature(base, "f", "Bob", {"f.txt": 3})
        base.write("main.txt", lines(1))
        base.commit("Alice", "main work")
        base.switch("f")
        base.git(
            "rebase", "-q", "main", env=Repo.identity("Bob", "2024-03-10 13:00:00")
        )
        base.switch("main")
        base.merge("Carol", "f", options=("--ff-only",))
        result = stats(base, monkeypatch)
        assert "Carol" not in result
        assert all(e["merges"] == 0 for e in result.values())
        assert result["Bob"]["commits"] == 1

    def test_merge_on_another_branch_counted_only_when_that_branch_is_analyzed(
        self, base, monkeypatch
    ):
        base.branch("develop")
        feature(base, "f", "Bob", {"f.txt": 1}, start="develop")
        base.switch("develop")
        base.merge("Carol", "f")
        base.switch("main")
        assert "Carol" not in stats(base, monkeypatch)
        base.switch("develop")
        assert stats(base, monkeypatch)["Carol"]["merges"] == 1

    def test_merges_respect_the_date_range(self, base, monkeypatch):
        for i, date in enumerate(
            [
                "2024-02-29 23:59:59",
                "2024-03-01 00:00:01",
                "2024-03-31 23:59:58",
                "2024-04-01 00:00:01",
            ]
        ):
            feature(base, f"f{i}", "Bob", {f"f{i}.txt": 1})
            base.merge("Carol", f"f{i}", date=date)
        carol = stats(base, monkeypatch, start="03/01/2024", end="03/31/2024")["Carol"]
        assert carol["merges"] == 2

    def test_username_option_by_name_and_email(self, base, monkeypatch):
        feature(base, "f", "Bob", {"f.txt": 1})
        base.merge("Carol", "f", email="carol@example.com")
        assert stats(base, monkeypatch, username="Carol")["Carol"]["merges"] == 1
        by_email = stats(base, monkeypatch, username="carol@example.com")
        assert by_email["carol@example.com"]["merges"] == 1
        assert stats(base, monkeypatch, username="Car")["Car"]["merges"] == 0

    def test_clean_keeps_someone_who_only_merged(self, base, monkeypatch):
        feature(base, "f", "Bob", {"f.txt": 1})
        base.merge("Carol", "f")
        result = stats(base, monkeypatch, clean=True)
        assert result["Carol"]["merges"] == 1

    def test_mailmap_applies_to_merges(self, base, monkeypatch):
        base.write(
            ".mailmap",
            "Carol <carol@example.com> <12345+carol@users.noreply.github.com>\n",
        )
        base.commit("Carol", "mailmap", email="carol@example.com")
        feature(base, "f", "Bob", {"f.txt": 1})
        base.merge("carol-gh", "f", email="12345+carol@users.noreply.github.com")
        result = stats(base, monkeypatch)
        assert "carol-gh" not in result
        assert (result["Carol"]["commits"], result["Carol"]["merges"]) == (1, 1)

    def test_totals_across_contributors(self, base, monkeypatch):
        feature(base, "a", "Bob", {"a.txt": 2})
        base.merge("Carol", "a")
        feature(base, "b", "Dan", {"b.txt": 3})
        base.merge("Alice", "b")
        result = stats(base, monkeypatch)
        assert sum(e["merges"] for e in result.values()) == 2
        assert sum(e["commits"] for e in result.values()) == 3  # base, a, b
        assert sum(e["insertions"] for e in result.values()) == 6


# ─── Exclusions: none, one, several, and with merges ─────────────────────────


class TestExclusionCounts:
    @pytest.fixture
    def mixed(self, base):
        """One commit per kind of file, all by Alice, on top of base.txt (1 line)."""
        for path, n in [
            ("code.py", 2),
            ("data.json", 4),
            ("nested/deep/config.json", 8),
            ("photo.jpg", 16),
            ("vendor/lib.js", 32),
            ("docs/guide.md", 64),
            ("README.md", 128),
            ("my notes.txt", 256),
        ]:
            base.write(path, lines(n))
            base.commit("Alice", f"add {path}")
        return base

    @pytest.mark.parametrize(
        "exclusions,expected",
        [
            ([], (9, 9, 511)),
            (["*.json"], (7, 7, 499)),
            (["config.json"], (8, 8, 503)),
            (["*.json", "*.jpg"], (6, 6, 483)),
            (["*.json", "*.jpg", "*.md"], (4, 4, 291)),
            (["vendor"], (8, 8, 479)),
            (["vendor/"], (8, 8, 479)),
            (["vendor/*"], (8, 8, 479)),
            (["docs/*.md"], (8, 8, 447)),
            (["my notes.txt"], (8, 8, 255)),
            (["*.nothing"], (9, 9, 511)),
        ],
        ids=lambda v: repr(v),
    )
    def test_exclusion_combinations(self, mixed, monkeypatch, exclusions, expected):
        alice = stats(mixed, monkeypatch, exclusions=exclusions)["Alice"]
        assert (alice["commits"], alice["files"], alice["insertions"]) == expected

    def test_commit_partly_excluded_counts_only_the_rest(self, base, monkeypatch):
        base.write("code.py", lines(2))
        base.write("photo.jpg", lines(10))
        base.write("data.json", lines(10))
        base.commit("Alice", "mixed")
        alice = stats(base, monkeypatch, exclusions=["*.jpg", "*.json"])["Alice"]
        assert counts(alice) == (2, 2, 3, 0)  # base + mixed, minus excluded files

    def test_exclusions_do_not_affect_merges(self, base, monkeypatch):
        feature(base, "code", "Bob", {"code.py": 2})
        base.merge("Carol", "code")
        feature(base, "images", "Bob", {"a.jpg": 5, "b.jpg": 5})
        base.merge("Carol", "images")
        for exclusions in ([], ["*.jpg"], ["*.jpg", "*.py", "*.txt"]):
            result = stats(base, monkeypatch, exclusions=exclusions)
            assert result["Carol"]["merges"] == 2, exclusions

    def test_exclusions_with_merges_count_commits_correctly(self, base, monkeypatch):
        # regression: with a path filter, git used to drop merge commits and
        # could hide commits behind them; counts must not depend on that
        feature(base, "code", "Bob", {"code.py": 2})
        base.merge("Carol", "code")  # main did not move
        feature(base, "images", "Bob", {"a.jpg": 5})
        base.write("main.txt", lines(1))
        base.commit("Alice", "main work")
        base.merge("Carol", "images")
        excluded = stats(base, monkeypatch, exclusions=["*.jpg"])
        assert counts(excluded["Bob"]) == (1, 1, 2, 0)  # images commit excluded
        assert counts(excluded["Alice"]) == (2, 2, 2, 0)
        assert excluded["Carol"]["merges"] == 2
        everything = stats(base, monkeypatch, exclusions=[])
        assert counts(everything["Bob"]) == (2, 2, 7, 0)
        assert everything["Carol"]["merges"] == 2


class TestExclusionOption:
    """The -x option on the command line: default, none, one, several."""

    @pytest.fixture
    def remote(self, tmp_path):
        r = Repo(tmp_path / "remotes" / "proj")
        for path, n in [
            ("code.py", 1),
            ("data.json", 2),
            ("photo.jpg", 4),
            ("notes.md", 8),
        ]:
            r.write(path, lines(n))
            r.commit("Alice", f"add {path}")
        r.branch("f")
        r.write("f.py", lines(16))
        r.commit("Bob", "f")
        r.switch("main")
        r.merge("Carol", "f")
        return r

    def run(self, monkeypatch, capsys, cwd, remote, *argv):
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "gitlogstats",
                "-r",
                remote.path,
                "-s",
                "01/01/2024",
                "-e",
                "12/31/2024",
                "-f",
                "json",
                *argv,
            ],
        )
        main()
        return {e["username"]: e for e in json.loads(capsys.readouterr().out)}

    @pytest.mark.parametrize(
        "argv,alice",
        [
            ([], (2, 9)),  # defaults exclude *.json and *.jpg
            (["-x", ""], (4, 15)),  # no exclusions at all
            (["-x", "*.md"], (3, 7)),  # replaces the defaults
            (["-x", "*.json,*.jpg,*.md"], (1, 1)),
            (["-x", " *.json , *.jpg ,, *.md "], (1, 1)),  # spaces, empty items
        ],
        ids=["default", "none", "one", "several", "messy"],
    )
    def test_exclusions(self, remote, tmp_path, monkeypatch, capsys, argv, alice):
        result = self.run(monkeypatch, capsys, tmp_path, remote, *argv)
        assert (result["Alice"]["commits"], result["Alice"]["insertions"]) == alice
        assert result["Bob"]["commits"] == 1
        assert result["Carol"]["merges"] == 1


# ─── GitHub pull requests (--github) ─────────────────────────────────────────

GITHUB_URL = "https://github.com/acme/widgets"
SLUG = "acme/widgets"
GITHUB_COLUMNS = [
    "github_username",
    "prs_opened",
    "prs_merged",
    "prs_closed_unmerged",
    "prs_self_merged",
]
PR_COLUMNS = GITHUB_COLUMNS[1:]
EMAIL_COLUMNS = ["git_email", "github_email"]
ACTIVITY_COLUMNS = ["pushes_to_default", "web_commits"]
NOT_INSTALLED = (
    "gitlogstats: --github needs the GitHub CLI (gh), which is not installed. "
    "Install it from https://cli.github.com and run 'gh auth login', "
    "or run without --github.\n"
)
NOT_SIGNED_IN = (
    "gitlogstats: --github needs the GitHub CLI (gh) to be signed in. "
    "Run 'gh auth login', or run without --github.\n"
)


def at(year, month, day, hour=12, minute=0, second=0):
    """The GitHub-style UTC timestamp of a moment given in local time."""
    local = datetime.datetime(year, month, day, hour, minute, second)
    utc = datetime.datetime.fromtimestamp(
        time.mktime(local.timetuple()), datetime.timezone.utc
    )
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(
    login, created, merged=None, closed=None, base="main", merged_by=None, commit=None
):
    """
    A pull request as the GitHub GraphQL API returns it. *commit* is the merge
    commit, as (hash, committer time).
    """
    return {
        "author": {"login": login, "__typename": "User"},
        "mergedBy": {"login": merged_by, "__typename": "User"} if merged_by else None,
        "state": "MERGED" if merged else ("CLOSED" if closed else "OPEN"),
        "createdAt": created,
        "mergedAt": merged,
        "closedAt": merged or closed,
        "baseRefName": base,
        "mergeCommit": {"oid": commit[0], "committedDate": commit[1]}
        if commit
        else None,
    }


def push(login, when, kind="push", ref="refs/heads/main"):
    """An entry of GitHub's repository activity record (STAT-14)."""
    actor = {"login": login, "type": "User"} if login else None
    return {"timestamp": when, "activity_type": kind, "actor": actor, "ref": ref}


def head(repo):
    return repo.git("rev-parse", "HEAD").strip()


def github_world(
    tmp_path,
    monkeypatch,
    repo,
    prs=(),
    users=None,
    contributors=(),
    linked=None,
    extra_routes=None,
    pushes=(),
):
    """
    Make GITHUB_URL clone *repo* (git URL rewriting in an isolated config) and
    install a fake gh that serves these pull requests, activity entries of the
    main branch (see push), user profiles ({login:
    {"name", "email"}}), contributor logins, commit links ({sha: login or
    None}) and any extra fake gh routes (e.g. errors). Returns the function
    listing the gh calls made.
    """
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(f'[url "{repo.path}"]\n\tinsteadOf = {GITHUB_URL}\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    routes = {
        f"graphql:{SLUG}": {"graphql_pages": [list(prs)]},
        f"repos/{SLUG}/activity?per_page=100&ref=refs/heads/main": {
            "body": list(pushes)
        },
        # branches that tests pass to -b have no activity
        f"repos/{SLUG}/activity?per_page=100&ref=refs/heads/dev": {"body": []},
        f"repos/{SLUG}/activity?per_page=100&ref=refs/heads/nope": {"body": []},
        f"repos/{SLUG}/contributors?per_page=100": {
            "body": [{"login": login} for login in contributors]
        },
    }
    for login, profile in (users or {}).items():
        routes[f"users/{login}"] = {"body": dict(profile, login=login)}
    for sha, login in (linked or {}).items():
        author = {"login": login} if login else None
        routes[f"repos/{SLUG}/commits/{sha}"] = {"body": {"author": author}}
    routes.update(extra_routes or {})
    return install_fake_gh(tmp_path, monkeypatch, routes)


def run_github(monkeypatch, capsys, tmp_path, *argv):
    """Run the command in a scratch directory; returns (stdout, stderr)."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.chdir(work)
    monkeypatch.setattr(sys, "argv", ["gitlogstats", *argv])
    main()
    captured = capsys.readouterr()
    return captured.out, captured.err


def rows_of(out):
    """JSON rows as tuples: username, github_username, commits and the PR counts."""
    return [
        (r["username"], r["github_username"], r["commits"])
        + tuple(r[c] for c in PR_COLUMNS)
        for r in json.loads(out)
    ]


DATES = ["-s", "01/01/2024", "-e", "12/31/2024"]


class TestGitHub:
    @pytest.fixture
    def widgets(self, tmp_path):
        return Repo(tmp_path / "remotes" / "widgets")

    def github(self, monkeypatch, capsys, tmp_path, *argv, url=GITHUB_URL):
        return run_github(
            monkeypatch, capsys, tmp_path, "-r", url, "--github", *DATES, *argv
        )

    # --- matching and combining

    def test_one_person_with_two_git_names_is_one_row(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("ada", "base", email="ada@laptop.example")
        first = head(widgets)
        widgets.branch("f")
        widgets.write("f.txt", lines(3))
        widgets.commit("ada", "work", email="ada@laptop.example")
        second = head(widgets)
        widgets.switch("main")
        # a pull request merged on the website: GitHub display name, noreply email
        widgets.merge(
            "Ada Lovelace",
            "f",
            message="Merge pull request #1 from acme/f",
            email="111+adal99@users.noreply.github.com",
            committer=("GitHub", "noreply@github.com"),
        )
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[
                pr("adal99", at(2024, 3, 5), merged=at(2024, 3, 6)),
                pr("adal99", at(2024, 3, 7)),
            ],
            contributors=["adal99"],
            linked={first: "adal99", second: "adal99"},
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        rows = json.loads(out)
        assert len(rows) == 1
        assert rows[0]["username"] == "ada"
        assert rows[0]["github_username"] == "adal99"
        assert (rows[0]["commits"], rows[0]["insertions"], rows[0]["merges"]) == (
            2,
            4,
            1,
        )
        assert [rows[0][c] for c in PR_COLUMNS] == [2, 1, 0, 0]
        assert err == ""

    def test_profile_rate_limit_leaves_github_columns_empty(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        # without the profile, Ada's display-name match would be lost and her
        # pull request silently credited to a GitHub-only row
        widgets.write("a.txt", lines(1))
        widgets.commit("Ada Lovelace", "work", email="ada@example.com")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[pr("adal99", at(2024, 3, 5))],
            extra_routes={
                "users/adal99": {
                    "error": "gh: API rate limit exceeded for user ID 1. (HTTP 403)\n"
                }
            },
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert rows_of(out) == [("Ada Lovelace", None, 1, None, None, None, None)]
        assert "no GitHub statistics for" in err
        assert "rate limit" in err

    def test_missing_profile_still_matches_by_username(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("adal99", "work", email="ada@example.com")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[pr("adal99", at(2024, 3, 5))],
            extra_routes={"users/adal99": {"error": "gh: Not Found (HTTP 404)\n"}},
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert rows_of(out) == [("adal99", "adal99", 1, 1, 0, 0, 0)]
        assert err == ""

    def test_unlinked_email_is_matched_by_username(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Carol99", "work", email="carol@example.com")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[pr("carol99", at(2024, 3, 5))],
            linked={head(widgets): None},  # GitHub does not link this email
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-v")
        assert rows_of(out) == [("Carol99", "carol99", 1, 1, 0, 0, 0)]

    def test_display_name_match(self, widgets, tmp_path, monkeypatch, capsys):
        widgets.write("a.txt", lines(1))
        widgets.commit("Ada Lovelace", "work", email="ada@example.com")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[pr("adal99", at(2024, 3, 5))],
            users={"adal99": {"name": "Lovelace, Ada", "email": None}},
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-v")
        assert rows_of(out) == [("Ada Lovelace", "adal99", 1, 1, 0, 0, 0)]
        assert "GitHub match: Ada Lovelace -> adal99 (display_name)" in err

    def test_pull_request_author_without_git_identity(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Eve", "work", email="eve@example.com")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[pr("zed", at(2024, 3, 5), merged=at(2024, 3, 6))],
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        data = json.loads(out)
        assert rows_of(out) == [("Eve", "", 1, 0, 0, 0, 0), ("", "zed", 0, 1, 1, 0, 0)]
        zed = data[1]
        assert (zed["repository"], zed["start_date"], zed["end_date"]) == (
            "widgets",
            "01/01/2024",
            "12/31/2024",
        )
        assert (zed["insertions"], zed["deletions"], zed["files"], zed["merges"]) == (
            0,
            0,
            0,
            0,
        )

    def test_git_author_without_github_match_has_zero_counts(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Eve", "work", email="eve@example.com")
        github_world(tmp_path, monkeypatch, widgets, contributors=["someone"])
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-v")
        assert rows_of(out) == [("Eve", "", 1, 0, 0, 0, 0)]

    def test_verbose_reports_tiers_unmatched_and_call_count(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Carol99", "work", email="carol@example.com")
        widgets.commit("Eve", "work", email="eve@example.com")
        calls = github_world(
            tmp_path, monkeypatch, widgets, prs=[pr("carol99", at(2024, 3, 5))]
        )
        _, err = self.github(monkeypatch, capsys, tmp_path, "-v")
        assert "GitHub match: Carol99 -> carol99 (username)" in err
        assert "GitHub unmatched: Eve" in err
        api_calls = [c for c in calls() if c[0] == "api"]
        assert f"GitHub API calls: {len(api_calls)}" in err

    def test_ambiguous_names_are_listed_with_verbose(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Ada Lovelace", "work", email="ada@example.com")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[pr("adal99", at(2024, 3, 5)), pr("lovelace1", at(2024, 3, 5))],
            users={
                "adal99": {"name": "Ada Lovelace", "email": None},
                "lovelace1": {"name": "Lovelace Ada", "email": None},
            },
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-v")
        assert "GitHub ambiguous: Ada Lovelace (display_name)" in err
        assert [r[:2] for r in rows_of(out)] == [
            ("Ada Lovelace", ""),
            ("", "adal99"),
            ("", "lovelace1"),
        ]

    # --- the options

    @pytest.fixture
    def team(self, widgets, tmp_path, monkeypatch):
        """Five git identities, four GitHub users and PRs near the range edges."""
        linked = {}

        def commit(author, email, login, name, date="2024-03-10 12:00:00"):
            widgets.write(name, lines(2))
            widgets.commit(author, name, date=date, email=email)
            linked[head(widgets)] = login

        commit("Frank", "frank@example.com", "frank-gh", "f.txt", "2023-05-05 12:00:00")
        commit("Dan", "dan@example.com", None, "d.txt", "2023-05-06 12:00:00")
        commit("Alice", "alice@example.com", "alice-gh", "a1.txt")
        commit("Alice", "alice@example.com", "alice-gh", "a2.txt")
        commit("A. Smith", "asmith@example.com", "alice-gh", "s.txt")
        commit("Bob", "bob@example.com", "bobby", "b.txt")
        prs = [
            # merged by herself
            pr("alice-gh", at(2024, 3, 5), merged=at(2024, 3, 6), merged_by="alice-gh"),
            pr("alice-gh", at(2024, 3, 7), base="dev"),
            pr("alice-gh", at(2024, 3, 1), closed=at(2024, 3, 2)),
            # created in 2023 but merged in the first second of the range
            # ... and merged by someone else
            pr(
                "bobby",
                at(2023, 12, 31, 23, 59, 59),
                merged=at(2024, 1, 1, 0, 0, 1),
                merged_by="alice-gh",
            ),
            # merged by himself, but before the range
            pr("bobby", at(2023, 12, 1), merged=at(2023, 12, 2), merged_by="bobby"),
            # created in the first second after the range
            pr("bobby", at(2025, 1, 1, 0, 0, 0)),
            pr("frank-gh", at(2024, 4, 1)),
            pr("pro", at(2024, 3, 8)),
            pr(
                "pro",
                at(2024, 3, 8),
                merged=at(2024, 3, 9),
                base="dev",
                merged_by="pro",
            ),
        ]
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=prs,
            contributors=["alice-gh", "bobby", "frank-gh"],
            linked=linked,
        )
        return widgets

    def test_pull_request_states_and_range_boundaries(
        self, team, tmp_path, monkeypatch, capsys
    ):
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert rows_of(out) == [
            ("Alice", "alice-gh", 3, 3, 1, 1, 1),  # open + merged + closed unmerged
            ("Bob", "bobby", 1, 0, 1, 0, 0),  # only the merge is inside the range
            ("Dan", "", 0, 0, 0, 0, 0),
            ("Frank", "frank-gh", 0, 1, 0, 0, 0),
            ("", "pro", 0, 2, 1, 0, 1),
        ]
        alice = json.loads(out)[0]
        assert (alice["insertions"], alice["files"]) == (6, 3)
        assert err == ""

    @pytest.mark.parametrize(
        "branch,alice",
        [
            ("main", (2, 1, 1, 1)),
            ("dev", (1, 0, 0, 0)),
            ("nope", (0, 0, 0, 0)),
        ],
    )
    def test_branch_filters_pull_requests_by_base(
        self, team, tmp_path, monkeypatch, capsys, branch, alice
    ):
        # the branch also selects what git analyses, so check the PR counts only
        team.git("branch", "dev")
        team.git("branch", "nope")
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-b", branch)
        assert tuple(json.loads(out)[0][c] for c in PR_COLUMNS) == alice

    def test_self_merged_counts_only_the_authors_own_merges_in_range(
        self, team, tmp_path, monkeypatch, capsys
    ):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        by_login = {r["github_username"]: r for r in json.loads(out)}
        # Alice merged her own PR; Bob's PR in range was merged by Alice, and
        # his own merge happened before the range; "pro" self-merged on dev
        assert {k: v["prs_self_merged"] for k, v in by_login.items()} == {
            "alice-gh": 1,
            "bobby": 0,
            "": 0,
            "frank-gh": 0,
            "pro": 1,
        }
        # a self-merge is also a merge, so it is never more than prs_merged
        assert all(r["prs_self_merged"] <= r["prs_merged"] for r in by_login.values())

    def test_branch_filter_applies_to_self_merges(
        self, team, tmp_path, monkeypatch, capsys
    ):
        team.git("branch", "dev")
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-b", "dev")
        by_login = {r["github_username"]: r for r in json.loads(out)}
        assert by_login["alice-gh"]["prs_self_merged"] == 0
        assert by_login["pro"]["prs_self_merged"] == 1
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-b", "main")
        by_login = {r["github_username"]: r for r in json.loads(out)}
        assert by_login["alice-gh"]["prs_self_merged"] == 1
        assert by_login["pro"]["prs_self_merged"] == 0

    def test_self_merge_is_reported_in_csv_and_markdown(
        self, team, tmp_path, monkeypatch, capsys
    ):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-u", "alice-gh")
        assert out.splitlines()[1].endswith(
            ",alice-gh,3,1,1,1,alice@example.com; asmith@example.com,,0,0"
        )
        out, _ = self.github(
            monkeypatch, capsys, tmp_path, "-u", "alice-gh", "-f", "markdown"
        )
        assert out.splitlines()[2].endswith(
            "| alice-gh | 3 | 1 | 1 | 1 | alice@example.com; asmith@example.com |  | 0 | 0 |"
        )

    @pytest.mark.parametrize(
        "user",
        ["Alice", "A. Smith", "asmith@example.com", "alice-gh", "ALICE-GH"],
    )
    def test_user_selects_the_combined_row(
        self, team, tmp_path, monkeypatch, capsys, user
    ):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-u", user)
        assert rows_of(out) == [("Alice", "alice-gh", 3, 3, 1, 1, 1)]

    def test_user_matches_github_only_row_by_login(
        self, team, tmp_path, monkeypatch, capsys
    ):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-u", "PRO")
        assert rows_of(out) == [("", "pro", 0, 2, 1, 0, 1)]

    @pytest.mark.parametrize("user", ["alice", "alice@example", "Smith", "nobody"])
    def test_user_must_match_exactly(self, team, tmp_path, monkeypatch, capsys, user):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-u", user)
        assert out == "[]\n"

    def test_clean_drops_only_rows_without_any_activity(
        self, team, tmp_path, monkeypatch, capsys
    ):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-c")
        # Dan has nothing; Frank has no commits in range but a pull request, and
        # keeps his own row; "pro" has a pull request and no git identity
        assert rows_of(out) == [
            ("Alice", "alice-gh", 3, 3, 1, 1, 1),
            ("Bob", "bobby", 1, 0, 1, 0, 0),
            ("Frank", "frank-gh", 0, 1, 0, 0, 0),
            ("", "pro", 0, 2, 1, 0, 1),
        ]

    def test_exclusions_do_not_affect_pull_requests(
        self, team, tmp_path, monkeypatch, capsys
    ):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-x", "*.txt")
        data = json.loads(out)
        assert (data[0]["commits"], data[0]["prs_opened"]) == (0, 3)

    # --- output formats

    def test_csv_and_markdown_append_the_github_columns(
        self, team, tmp_path, monkeypatch, capsys
    ):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-u", "Bob")
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,"
            "files,merges,github_username,prs_opened,prs_merged,prs_closed_unmerged,prs_self_merged,git_email,github_email,"
            "pushes_to_default,web_commits\n"
            "Bob,widgets,01/01/2024,12/31/2024,1,2,0,1,0,bobby,0,1,0,0,bob@example.com,,0,0\n"
        )
        out, _ = self.github(
            monkeypatch, capsys, tmp_path, "-u", "Bob", "-f", "markdown"
        )
        header, _, row = out.splitlines()
        assert header.endswith(
            "| merges | github_username | prs_opened | prs_merged | prs_closed_unmerged | prs_self_merged | git_email | github_email | pushes_to_default | web_commits |"
        )
        assert row.endswith(
            "| 0 | bobby | 0 | 1 | 0 | 0 | bob@example.com |  | 0 | 0 |"
        )

    def test_empty_csv_still_has_the_github_columns(
        self, team, tmp_path, monkeypatch, capsys
    ):
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-u", "nobody")
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,"
            "files,merges,github_username,prs_opened,prs_merged,prs_closed_unmerged,prs_self_merged,git_email,github_email,"
            "pushes_to_default,web_commits\n"
        )

    # --- email columns (STAT-13)

    def emails_of(self, out):
        """JSON rows as (username, github_username, git_email, github_email)."""
        return [
            (r["username"], r["github_username"], r["git_email"], r["github_email"])
            for r in json.loads(out)
        ]

    @pytest.fixture
    def ada(self, widgets, tmp_path, monkeypatch):
        """Ada: two git names and three addresses, one only differing in case."""
        # the old commit goes first: git stops reading at a too-old commit
        widgets.write("e.txt", lines(1))
        widgets.commit(
            "ada", "old", date="2020-01-01 12:00:00", email="a.old@x.example"
        )
        widgets.write("a.txt", lines(1))
        widgets.commit("ada", "base", email="Ada@x.example")
        first = head(widgets)
        widgets.write("b.txt", lines(2))
        widgets.commit("ada", "again", email="ada@x.example")
        widgets.write("c.txt", lines(3))
        widgets.commit(
            "Ada Lovelace", "web", email="111+adal99@users.noreply.github.com"
        )
        third = head(widgets)
        widgets.write("d.txt", lines(1))
        widgets.commit("Zoe", "other", email="zoe@x.example")
        return widgets, {first: "adal99", third: "adal99"}

    def ada_world(self, ada, tmp_path, monkeypatch, users, extra_prs=()):
        widgets, linked = ada
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[pr("adal99", at(2024, 3, 5)), *extra_prs],
            users=users,
            contributors=["adal99"],
            linked=linked,
        )

    def test_combined_row_lists_every_git_email_sorted_and_deduplicated(
        self, ada, tmp_path, monkeypatch, capsys
    ):
        self.ada_world(ada, tmp_path, monkeypatch, {"adal99": {"name": None}})
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        rows = self.emails_of(out)
        # case-insensitive order and one of the two case variants; the 2020
        # address is outside the date range; the noreply address is included
        assert rows[0] == (
            "ada",
            "adal99",
            "111+adal99@users.noreply.github.com; a.old@x.example; Ada@x.example",
            "",
        )
        # an unmatched git row has no GitHub email
        assert rows[1] == ("Zoe", "", "zoe@x.example", "")

    def test_public_profile_email_is_github_email(
        self, ada, tmp_path, monkeypatch, capsys
    ):
        self.ada_world(
            ada,
            tmp_path,
            monkeypatch,
            {"adal99": {"name": None, "email": "ada@pub.example"}},
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert self.emails_of(out)[0][3] == "ada@pub.example"

    def test_github_only_row_has_empty_git_email(
        self, ada, tmp_path, monkeypatch, capsys
    ):
        self.ada_world(
            ada,
            tmp_path,
            monkeypatch,
            {
                "adal99": {"name": None},
                "pro": {"name": None, "email": "pro@pub.example"},
            },
            extra_prs=[pr("pro", at(2024, 3, 8))],
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert self.emails_of(out)[-1] == ("", "pro", "", "pro@pub.example")

    def test_matched_login_that_was_not_a_candidate_gets_its_profile(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        # GitHub links the address to "ghost-writer", who has no pull request
        # and is not a listed contributor, so the profile is fetched afterwards
        widgets.write("a.txt", lines(1))
        widgets.commit("Quinn", "work", email="q@x.example")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[],
            users={"ghost-writer": {"name": None, "email": "gw@pub.example"}},
            linked={head(widgets): "ghost-writer"},
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert self.emails_of(out) == [
            ("Quinn", "ghost-writer", "q@x.example", "gw@pub.example")
        ]

    def test_missing_profile_of_matched_login_leaves_github_email_empty(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Quinn", "work", email="q@x.example")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            linked={head(widgets): "ghost-writer"},
            extra_routes={
                "users/ghost-writer": {"error": "gh: Not Found (HTTP 404)\n"}
            },
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert self.emails_of(out) == [("Quinn", "ghost-writer", "q@x.example", "")]
        assert err == ""

    def test_profile_error_of_matched_login_makes_repository_unavailable(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Quinn", "work", email="q@x.example")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            linked={head(widgets): "ghost-writer"},
            extra_routes={
                "users/ghost-writer": {"error": "gh: rate limit exceeded (HTTP 403)\n"}
            },
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert self.emails_of(out) == [("Quinn", None, "q@x.example", None)]
        assert "rate limit" in err

    def test_csv_round_trips_the_joined_emails(
        self, ada, tmp_path, monkeypatch, capsys
    ):
        self.ada_world(
            ada,
            tmp_path,
            monkeypatch,
            {"adal99": {"name": None, "email": "ada@pub.example"}},
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path)
        table = list(csv.DictReader(io.StringIO(out)))
        assert list(table[0])[-9:] == GITHUB_COLUMNS + EMAIL_COLUMNS + ACTIVITY_COLUMNS
        assert table[0]["git_email"].split("; ") == [
            "111+adal99@users.noreply.github.com",
            "a.old@x.example",
            "Ada@x.example",
        ]
        assert table[0]["github_email"] == "ada@pub.example"
        assert (table[1]["git_email"], table[1]["github_email"]) == (
            "zoe@x.example",
            "",
        )

    def test_emails_do_not_count_as_activity_for_clean(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Old", "work", date="2020-01-01 12:00:00", email="old@x.example")
        github_world(tmp_path, monkeypatch, widgets)
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert self.emails_of(out) == [("Old", "", "old@x.example", "")]
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-c")
        assert out == "[]\n"

    def test_without_github_there_are_no_email_columns(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Alice", "work", email="alice@example.com")
        github_world(tmp_path, monkeypatch, widgets)
        out, _ = run_github(monkeypatch, capsys, tmp_path, "-r", GITHUB_URL, *DATES)
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,"
            "files,merges\n"
            "Alice,widgets,01/01/2024,12/31/2024,1,1,0,1,0\n"
        )

    # --- repositories GitHub cannot be asked about

    def test_local_repository_has_empty_github_columns(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(3))
        widgets.commit("Alice", "work", email="alice@example.com")
        calls = github_world(tmp_path, monkeypatch, widgets)
        argv = ["-r", widgets.path, "--github", *DATES]
        out, err = run_github(monkeypatch, capsys, tmp_path, *argv, "-f", "json")
        assert err == (
            f"gitlogstats: no GitHub statistics for {widgets.path}: "
            "not a github.com repository\n"
        )
        row = json.loads(out)[0]
        assert (row["username"], row["commits"], row["insertions"]) == ("Alice", 1, 3)
        assert [row[c] for c in GITHUB_COLUMNS] == [None] * 5
        assert [row[c] for c in ACTIVITY_COLUMNS] == [None, None]
        assert [c for c in calls() if c[0] == "api"] == []
        out, _ = run_github(monkeypatch, capsys, tmp_path, *argv)
        assert (
            out.splitlines()[1]
            == "Alice,widgets,01/01/2024,12/31/2024,1,3,0,1,0,,,,,,alice@example.com,,,"
        )
        out, _ = run_github(monkeypatch, capsys, tmp_path, *argv, "-f", "markdown")
        assert out.splitlines()[2].endswith(
            "| 0 |  |  |  |  |  | alice@example.com |  |  |  |"
        )

    def test_github_failure_for_one_repository_does_not_stop_the_next(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(2))
        widgets.commit("Alice", "work", email="alice@example.com")
        other = Repo(tmp_path / "remotes" / "other")
        other.write("o.txt", lines(5))
        other.commit("Bob", "work", email="bob@example.com")
        calls = github_world(tmp_path, monkeypatch, widgets)
        # take away the pull request route: gh answers 404
        config = tmp_path / "fake-gh-config" / "config.json"
        routes = json.loads(config.read_text())
        del routes["routes"][f"graphql:{SLUG}"]
        config.write_text(json.dumps(routes))
        repofile = tmp_path / "repos.txt"
        repofile.write_text(f"{GITHUB_URL}\n{other.path}\n")
        out, err = run_github(
            monkeypatch, capsys, tmp_path, "-rf", str(repofile), "--github", *DATES,
            "-f", "json",
        )  # fmt: skip
        assert f"gitlogstats: no GitHub statistics for {GITHUB_URL}: " in err
        assert "404" in err
        assert f"no GitHub statistics for {other.path}: not a github.com" in err
        data = json.loads(out)
        assert [(r["username"], r["repository"], r["commits"]) for r in data] == [
            ("Alice", "widgets", 1),
            ("Bob", "other", 1),
        ]
        assert all(
            r[c] is None for r in data for c in GITHUB_COLUMNS + ACTIVITY_COLUMNS
        )
        # STAT-13: git_email is still filled in, github_email is unavailable
        assert [(r["git_email"], r["github_email"]) for r in data] == [
            ("alice@example.com", None),
            ("bob@example.com", None),
        ]

    def test_clean_and_user_apply_to_unavailable_rows_too(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        # the old commit goes first: git stops reading history at a too-old commit
        widgets.write("b.txt", lines(2))
        widgets.commit(
            "Old", "work", date="2020-01-01 12:00:00", email="old@example.com"
        )
        widgets.write("a.txt", lines(2))
        widgets.commit("Alice", "work", email="alice@example.com")
        github_world(tmp_path, monkeypatch, widgets)
        base = ["-r", widgets.path, "--github", *DATES, "-f", "json"]
        out, _ = run_github(monkeypatch, capsys, tmp_path, *base, "-c")
        assert [r["username"] for r in json.loads(out)] == ["Alice"]
        out, _ = run_github(
            monkeypatch, capsys, tmp_path, *base, "-u", "old@example.com"
        )
        assert [r["username"] for r in json.loads(out)] == ["Old"]

    # --- pushes and website commits (STAT-14, STAT-15)

    def rows_by_name(self, out):
        return {r["username"] or r["github_username"]: r for r in json.loads(out)}

    def test_pushes_count_only_pushes_and_force_pushes_in_range(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("adal99", "work", email="ada@example.com")
        activity = [
            push("adal99", at(2024, 3, 1)),
            push("ADAL99", at(2024, 3, 2), kind="force_push"),  # case-insensitive
            push("adal99", at(2024, 3, 3), kind="branch_creation"),
            push("adal99", at(2024, 3, 4), kind="pr_merge"),
            push("adal99", at(2024, 3, 5), kind="merge_queue_merge"),
            push("adal99", at(2024, 3, 6), kind="branch_deletion"),
            push("adal99", at(2024, 1, 1, 0, 0, 0)),  # first second of the range
            push("adal99", at(2024, 12, 31, 23, 59, 59)),  # last second
            push("adal99", at(2023, 12, 31, 23, 59, 59)),  # just before
            push("adal99", at(2025, 1, 1, 0, 0, 0)),  # just after
            push("zed", at(2024, 6, 1)),  # no commits, no pull requests
            push(None, at(2024, 6, 2)),  # a deleted account
        ]
        calls = github_world(
            tmp_path, monkeypatch, widgets, pushes=activity, contributors=["adal99"]
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        rows = self.rows_by_name(out)
        assert err == ""
        assert rows["adal99"]["pushes_to_default"] == 4
        assert rows["zed"]["pushes_to_default"] == 1
        assert rows["zed"]["commits"] == 0 and rows["zed"]["username"] == ""
        assert rows["ghost"]["pushes_to_default"] == 1
        assert [r["pushes_to_default"] for r in json.loads(out)] == [4, 1, 1]
        # one paginated request for the analyzed branch's activity
        assert [
            "api",
            f"repos/{SLUG}/activity?per_page=100&ref=refs/heads/main",
            "--paginate",
        ] in calls()

    def test_pushes_are_credited_to_the_combined_row(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("ada", "one", email="111+adal99@users.noreply.github.com")
        widgets.write("b.txt", lines(1))
        widgets.commit(
            "Ada Lovelace", "two", email="111+adal99@users.noreply.github.com"
        )
        widgets.write("c.txt", lines(1))
        widgets.commit("Bob", "three", email="bob@example.com")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[pr("adal99", at(2024, 3, 5))],
            contributors=["adal99"],
            pushes=[push("adal99", at(2024, 3, 1)), push("adal99", at(2024, 3, 2))],
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        data = json.loads(out)
        assert [(r["username"], r["pushes_to_default"]) for r in data] == [
            ("Ada Lovelace", 2),
            ("Bob", 0),
        ]
        assert data[0]["prs_opened"] == 1

    def test_pushes_use_the_branch_that_is_analyzed(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Alice", "work", email="alice@example.com")
        widgets.git("branch", "dev")
        calls = github_world(
            tmp_path,
            monkeypatch,
            widgets,
            pushes=[push("alice-gh", at(2024, 3, 1))],
            extra_routes={
                f"repos/{SLUG}/activity?per_page=100&ref=refs/heads/dev": {
                    "body": [push("dev-user", at(2024, 3, 1), ref="refs/heads/dev")] * 3
                }
            },
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-b", "dev")
        rows = self.rows_by_name(out)
        assert rows["dev-user"]["pushes_to_default"] == 3
        assert "alice-gh" not in rows
        refs = [c[1] for c in calls() if "/activity" in c[1]]
        assert refs == [f"repos/{SLUG}/activity?per_page=100&ref=refs/heads/dev"]

    def test_pushes_to_a_detached_head_are_zero_and_not_requested(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Alice", "work", email="alice@example.com")
        widgets.git("tag", "v1")
        calls = github_world(
            tmp_path, monkeypatch, widgets, pushes=[push("alice-gh", at(2024, 3, 1))]
        )
        out, err = self.github(
            monkeypatch, capsys, tmp_path, "-f", "json", "-b", "v1", "-v"
        )
        assert [(r["username"], r["pushes_to_default"]) for r in json.loads(out)] == [
            ("Alice", 0)
        ]
        assert not [c for c in calls() if "/activity" in c[1]]
        # the skipped activity request is not counted as an API call
        api_calls = [c for c in calls() if c[0] == "api"]
        assert f"GitHub API calls: {len(api_calls)}" in err

    def test_unreadable_activity_makes_both_new_columns_empty(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Alice", "work", email="alice@example.com")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            extra_routes={
                f"repos/{SLUG}/activity?per_page=100&ref=refs/heads/main": {
                    "error": "gh: Resource not accessible (HTTP 403)\n"
                }
            },
        )
        out, err = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        row = json.loads(out)[0]
        assert (row["pushes_to_default"], row["web_commits"]) == (None, None)
        assert row["commits"] == 1 and row["prs_opened"] is None
        assert f"no GitHub statistics for {GITHUB_URL}" in err and "403" in err

    def web(self, widgets, author, name, email, when="2024-03-10 12:00:00", **kw):
        """Commit a new file as *author*, created by GitHub's website."""
        widgets.write(name, lines(2))
        widgets.commit(
            author,
            f"Update {name}",
            date=when,
            email=email,
            committer=("GitHub", "noreply@github.com"),
            **kw,
        )

    def test_website_commits_count_commits_github_created(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(2))
        widgets.commit("Alice", "local", email="alice@example.com")
        self.web(widgets, "Alice", "b.txt", "alice@example.com")
        self.web(widgets, "Alice", "c.txt", "alice@example.com")
        widgets.write("d.txt", lines(2))
        widgets.commit(
            "Bob",
            "local",
            email="bob@example.com",
            committer=("Bob", "bob@example.com"),
        )
        self.web(widgets, "Bob", "e.txt", "bob@example.com")
        github_world(tmp_path, monkeypatch, widgets)
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        rows = self.rows_by_name(out)
        assert (rows["Alice"]["commits"], rows["Alice"]["web_commits"]) == (3, 2)
        assert (rows["Bob"]["commits"], rows["Bob"]["web_commits"]) == (2, 1)
        assert all(r["web_commits"] <= r["commits"] for r in rows.values())

    def test_a_pull_request_merge_result_is_not_a_website_commit(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(2))
        widgets.commit("Alice", "local", email="alice@example.com")
        # squash merge of a pull request: GitHub commits it at the merge time
        self.web(widgets, "Alice", "s.txt", "alice@example.com", "2024-03-12 09:30:00")
        # a rebase merge of two commits, both committed at the merge time
        self.web(widgets, "Alice", "r1.txt", "alice@example.com", "2024-03-14 10:00:01")
        self.web(widgets, "Alice", "r2.txt", "alice@example.com", "2024-03-14 10:00:01")
        # a real website edit
        self.web(widgets, "Alice", "w.txt", "alice@example.com", "2024-03-16 11:00:00")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[
                pr("alice-gh", at(2024, 3, 11), merged=at(2024, 3, 12, 9, 30, 0)),
                pr("alice-gh", at(2024, 3, 13), merged=at(2024, 3, 14, 10, 0, 0)),
            ],
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        alice = self.rows_by_name(out)["Alice"]
        assert (alice["commits"], alice["web_commits"]) == (5, 1)

    def test_merge_commit_is_found_by_hash_even_when_merged_later(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(2))
        widgets.commit("Alice", "local", email="alice@example.com")
        # GitHub committed the squash 12 seconds before it stamped the merge
        self.web(widgets, "Alice", "s.txt", "alice@example.com", "2024-03-12 09:30:00")
        squash = head(widgets)
        # a rebase merge: last commit is the merge commit, the other is 1 s apart
        self.web(widgets, "Alice", "r1.txt", "alice@example.com", "2024-03-14 10:00:00")
        self.web(widgets, "Alice", "r2.txt", "alice@example.com", "2024-03-14 10:00:01")
        rebase = head(widgets)
        self.web(widgets, "Alice", "w.txt", "alice@example.com", "2024-03-16 11:00:00")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[
                pr(
                    "alice-gh",
                    at(2024, 3, 11),
                    merged=at(2024, 3, 12, 9, 30, 12),
                    commit=(squash, at(2024, 3, 12, 9, 30, 0)),
                ),
                pr(
                    "alice-gh",
                    at(2024, 3, 13),
                    merged=at(2024, 3, 14, 10, 0, 9),
                    commit=(rebase, at(2024, 3, 14, 10, 0, 1)),
                ),
            ],
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        alice = self.rows_by_name(out)["Alice"]
        assert (alice["commits"], alice["web_commits"]) == (5, 1)

    def test_old_head_commit_named_as_merge_commit_is_still_a_website_commit(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(2))
        widgets.commit("Alice", "local", email="alice@example.com")
        # a website edit that reached main directly; a pull request holding
        # it was merged 16 hours later, and GitHub names the edit as its
        # merge commit although the merge created nothing
        self.web(widgets, "Alice", "w.txt", "alice@example.com", "2024-03-12 09:30:00")
        edit = head(widgets)
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[
                pr(
                    "alice-gh",
                    at(2024, 3, 11),
                    merged=at(2024, 3, 13, 1, 30, 0),
                    commit=(edit, at(2024, 3, 12, 9, 30, 0)),
                )
            ],
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert self.rows_by_name(out)["Alice"]["web_commits"] == 1

    def test_merge_time_tolerance(self, widgets, tmp_path, monkeypatch, capsys):
        widgets.write("a.txt", lines(2))
        widgets.commit("Alice", "local", email="alice@example.com")
        self.web(widgets, "Alice", "t2.txt", "alice@example.com", "2024-03-12 09:30:02")
        self.web(widgets, "Alice", "t3.txt", "alice@example.com", "2024-03-14 10:00:03")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[
                pr("alice-gh", at(2024, 3, 11), merged=at(2024, 3, 12, 9, 30, 0)),
                pr("alice-gh", at(2024, 3, 13), merged=at(2024, 3, 14, 10, 0, 0)),
                pr("alice-gh", at(2024, 3, 15)),  # never merged
            ],
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        # 2 seconds after a merge is that merge's result; 3 seconds is an edit
        assert self.rows_by_name(out)["Alice"]["web_commits"] == 1

    def test_merge_commits_exclusions_and_range_limit_website_commits(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        # outside the date range; first, as git stops reading at a too-old commit
        self.web(
            widgets, "Alice", "old.txt", "alice@example.com", "2023-06-01 12:00:00"
        )
        widgets.write("a.txt", lines(2))
        widgets.commit("Alice", "local", email="alice@example.com")
        widgets.branch("f")
        self.web(widgets, "Bob", "f.txt", "bob@example.com", "2024-03-11 12:00:00")
        widgets.switch("main")
        # GitHub's merge commit is not a commit, so it is not a website commit
        widgets.merge(
            "Alice",
            "f",
            message="Merge pull request #1 from acme/f",
            date="2024-03-12 12:00:00",
            email="alice@example.com",
            committer=("GitHub", "noreply@github.com"),
        )
        # only an excluded file changed
        widgets.write("data.json", "{}\n")
        widgets.commit(
            "Alice",
            "edit data",
            date="2024-03-13 12:00:00",
            email="alice@example.com",
            committer=("GitHub", "NoReply@GitHub.com"),
        )
        # case of the committer address does not matter
        self.web(widgets, "Alice", "g.txt", "alice@example.com", "2024-03-14 12:00:00")
        widgets.write("h.txt", lines(1))
        widgets.commit(
            "Alice",
            "upper case",
            date="2024-03-15 12:00:00",
            email="alice@example.com",
            committer=("GitHub", "NOREPLY@GITHUB.COM"),
        )
        github_world(tmp_path, monkeypatch, widgets)
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        rows = self.rows_by_name(out)
        assert (rows["Alice"]["commits"], rows["Alice"]["web_commits"]) == (3, 2)
        assert (rows["Alice"]["merges"], rows["Bob"]["web_commits"]) == (1, 1)

    def test_website_commits_are_summed_over_combined_identities(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        email = "111+adal99@users.noreply.github.com"
        widgets.write("a.txt", lines(2))
        widgets.commit("ada", "local", email="ada@laptop.example")
        self.web(widgets, "ada", "b.txt", email)
        self.web(widgets, "Ada Lovelace", "c.txt", email)
        self.web(widgets, "Ada Lovelace", "d.txt", email)
        github_world(
            tmp_path, monkeypatch, widgets, contributors=["adal99"],
            linked={head(widgets): "adal99"},
        )  # fmt: skip
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        data = json.loads(out)
        assert len(data) == 1
        assert (data[0]["username"], data[0]["github_username"]) == (
            "Ada Lovelace",
            "adal99",
        )
        assert (data[0]["commits"], data[0]["web_commits"]) == (4, 3)

    def test_a_commit_github_made_when_it_created_the_repository_counts(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        # a root commit made through the website was still made on the website
        self.web(widgets, "Alice", "README.md", "alice@example.com")
        github_world(tmp_path, monkeypatch, widgets)
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json")
        assert self.rows_by_name(out)["Alice"]["web_commits"] == 1

    def test_activity_columns_count_as_activity_for_clean(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Old", "work", date="2020-01-01 12:00:00", email="old@x.example")
        github_world(
            tmp_path, monkeypatch, widgets, pushes=[push("zed", at(2024, 6, 1))]
        )
        out, _ = self.github(monkeypatch, capsys, tmp_path, "-f", "json", "-c")
        assert [
            (r["github_username"], r["pushes_to_default"]) for r in json.loads(out)
        ] == [("zed", 1)]

    def test_without_github_there_are_no_activity_columns(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        self.web(widgets, "Alice", "a.txt", "alice@example.com")
        calls = github_world(tmp_path, monkeypatch, widgets)
        out, _ = run_github(
            monkeypatch, capsys, tmp_path, "-r", GITHUB_URL, *DATES, "-f", "json"
        )
        assert list(json.loads(out)[0]) == [
            "username", "repository", "start_date", "end_date", "commits",
            "insertions", "deletions", "files", "merges",
        ]  # fmt: skip
        assert calls() == []

    # --- gh missing or signed out

    def run_expecting_exit(self, tmp_path, monkeypatch, capsys, widgets):
        with pytest.raises(SystemExit) as exc:
            run_github(
                monkeypatch, capsys, tmp_path, "-r", widgets.path, "--github", *DATES
            )
        captured = capsys.readouterr()
        assert exc.value.code == 1
        assert captured.out == ""
        assert not (tmp_path / "work" / "repos").exists()
        return captured.err

    def test_gh_not_installed(self, widgets, tmp_path, monkeypatch, capsys):
        widgets.write("a.txt", lines(1))
        widgets.commit("Alice", "work")
        only_git = tmp_path / "only-git"
        only_git.mkdir()
        (only_git / "git").symlink_to(shutil.which("git"))
        monkeypatch.setenv("PATH", str(only_git))
        err = self.run_expecting_exit(tmp_path, monkeypatch, capsys, widgets)
        assert err == NOT_INSTALLED

    def test_gh_signed_out(self, widgets, tmp_path, monkeypatch, capsys):
        widgets.write("a.txt", lines(1))
        widgets.commit("Alice", "work")
        calls = install_fake_gh(tmp_path, monkeypatch, auth_ok=False)
        err = self.run_expecting_exit(tmp_path, monkeypatch, capsys, widgets)
        assert err == NOT_SIGNED_IN
        assert calls() == [["auth", "status"]]

    # --- without --github

    def test_without_github_nothing_changes_and_gh_is_never_run(
        self, widgets, tmp_path, monkeypatch, capsys
    ):
        widgets.write("a.txt", lines(3))
        widgets.commit("Alice", "work", email="alice@example.com")
        calls = github_world(tmp_path, monkeypatch, widgets)
        out, err = run_github(monkeypatch, capsys, tmp_path, "-r", GITHUB_URL, *DATES)
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,files,merges\n"
            "Alice,widgets,01/01/2024,12/31/2024,1,3,0,1,0\n"
        )
        assert err == "" and "github" not in out
        assert calls() == []

    # --- the parser's new pieces

    def test_get_identities_lists_names_with_emails_and_a_commit_each(
        self, widgets, monkeypatch
    ):
        widgets.write("a.txt", lines(1))
        widgets.commit("Alice", "one", email="a@home.example")
        first = head(widgets)
        widgets.write("b.txt", lines(1))
        widgets.commit("Alice", "two", email="a@work.example")
        widgets.write("c.txt", lines(1))
        widgets.commit("Bob", "three", email="b@work.example")
        monkeypatch.chdir(widgets.path)
        parser = GitLogsParser(widgets.path, "01/01/2024", "12/31/2024", None)
        identities = parser.get_identities()
        assert {n: set(e) for n, e in identities.items()} == {
            "Alice": {"a@home.example", "a@work.example"},
            "Bob": {"b@work.example"},
        }
        assert identities["Alice"]["a@home.example"] == first
        assert set(identities) == set(parser.get_contributors())


# ─── Aggregated results (OUT-6) ──────────────────────────────────────────────

COUNT_COLUMNS = ["commits", "insertions", "deletions", "files", "merges"]


def totals(rows, key):
    """Sum each count of unaggregated JSON rows, per value of *key*."""
    sums = {}
    for row in rows:
        found = sums.setdefault(row[key], {c: 0 for c in COUNT_COLUMNS})
        for column in COUNT_COLUMNS:
            found[column] += row[column]
    return sums


class TestAggregate:
    @pytest.fixture
    def repofile(self, tmp_path):
        """Two repositories sharing Alice; Carol is active only before 2024."""
        one = Repo(tmp_path / "remotes" / "one")
        one.write("a.txt", lines(3))
        one.commit("Alice", "add a")
        one.branch("feature")
        one.write("a.txt", lines(1) + lines(2, "changed"))
        one.write("b.txt", lines(4))
        one.commit("Alice", "change a, add b")
        one.switch("main")
        one.merge("Bob", "feature")
        one.write("c.txt", lines(1))
        one.commit("Bob", "add c")
        two = Repo(tmp_path / "remotes" / "two")
        two.write("old.txt", lines(9))
        two.commit("Carol", "old work", date="2020-01-01 12:00:00")
        two.write("d.txt", lines(2))
        two.write("e.txt", lines(5))
        two.commit("Alice", "add d and e")
        path = tmp_path / "repos.txt"
        path.write_text(f"{one.path}\n{two.path}\n")
        return str(path)

    def run(self, monkeypatch, capsys, tmp_path, repofile, *argv):
        out, _ = run_github(
            monkeypatch, capsys, tmp_path, "-rf", repofile, *DATES, *argv
        )
        return out

    def test_developer_totals_are_sums_of_the_unaggregated_rows(
        self, repofile, tmp_path, monkeypatch, capsys
    ):
        plain = json.loads(
            self.run(monkeypatch, capsys, tmp_path, repofile, "-f", "json")
        )
        out = self.run(
            monkeypatch, capsys, tmp_path, repofile, "-f", "json", "-a", "developer"
        )
        rows = json.loads(out)
        assert [r["username"] for r in rows] == ["Alice", "Bob", "Carol"]
        sums = totals(plain, "username")
        for row in rows:
            assert {c: row[c] for c in COUNT_COLUMNS} == sums[row["username"]]
            assert "repository" not in row
        alice = rows[0]
        # 1 + 2 + 1 commits; 3 + (2 + 4) + (2 + 5) lines; 1 + 2 + 2 files
        assert [alice[c] for c in COUNT_COLUMNS] == [3, 16, 2, 5, 0]
        assert alice["repositories"] == 2
        assert [rows[1][c] for c in COUNT_COLUMNS] == [1, 1, 0, 1, 1]
        # Carol is listed (no -c) but was not active in any repository
        assert (rows[2]["commits"], rows[2]["repositories"]) == (0, 0)

    def test_repository_totals_are_sums_over_contributors(
        self, repofile, tmp_path, monkeypatch, capsys
    ):
        plain = json.loads(
            self.run(monkeypatch, capsys, tmp_path, repofile, "-f", "json")
        )
        out = self.run(
            monkeypatch, capsys, tmp_path, repofile, "-f", "json", "-a", "repository"
        )
        rows = json.loads(out)
        assert [(r["repository"], r["contributors"]) for r in rows] == [
            ("one", 2),
            ("two", 1),  # Carol is listed (no -c) but inactive
        ]
        sums = totals(plain, "repository")
        for row in rows:
            assert {c: row[c] for c in COUNT_COLUMNS} == sums[row["repository"]]
            assert "username" not in row
        assert [rows[0][c] for c in COUNT_COLUMNS] == [3, 10, 2, 4, 1]

    def test_csv_and_markdown_columns(self, repofile, tmp_path, monkeypatch, capsys):
        out = self.run(monkeypatch, capsys, tmp_path, repofile, "-a", "developer")
        assert out.splitlines() == [
            "username,start_date,end_date,commits,insertions,deletions,files,merges,repositories",
            "Alice,01/01/2024,12/31/2024,3,16,2,5,0,2",
            "Bob,01/01/2024,12/31/2024,1,1,0,1,1,1",
            "Carol,01/01/2024,12/31/2024,0,0,0,0,0,0",
        ]
        out = self.run(
            monkeypatch,
            capsys,
            tmp_path,
            repofile,
            "-a",
            "repository",
            "-f",
            "markdown",
        )
        assert out.splitlines()[0] == (
            "| repository | start_date | end_date | commits | insertions | deletions"
            " | files | merges | contributors |"
        )
        assert (
            out.splitlines()[2]
            == "| one | 01/01/2024 | 12/31/2024 | 3 | 10 | 2 | 4 | 1 | 2 |"
        )

    def test_clean_applies_before_counting(
        self, repofile, tmp_path, monkeypatch, capsys
    ):
        out = self.run(
            monkeypatch,
            capsys,
            tmp_path,
            repofile,
            "-c",
            "-f",
            "json",
            "-a",
            "repository",
        )
        assert [(r["repository"], r["contributors"]) for r in json.loads(out)] == [
            ("one", 2),
            ("two", 1),
        ]
        out = self.run(
            monkeypatch,
            capsys,
            tmp_path,
            repofile,
            "-c",
            "-f",
            "json",
            "-a",
            "developer",
        )
        assert [r["username"] for r in json.loads(out)] == ["Alice", "Bob"]

    def test_user_gives_one_developer_or_their_share_per_repository(
        self, repofile, tmp_path, monkeypatch, capsys
    ):
        argv = ["-u", "Alice", "-f", "json", "-a"]
        out = self.run(monkeypatch, capsys, tmp_path, repofile, *argv, "developer")
        assert [
            (r["username"], r["commits"], r["repositories"]) for r in json.loads(out)
        ] == [("Alice", 3, 2)]
        out = self.run(monkeypatch, capsys, tmp_path, repofile, *argv, "repository")
        assert [
            (r["repository"], r["commits"], r["contributors"]) for r in json.loads(out)
        ] == [("one", 2, 1), ("two", 1, 1)]

    @pytest.mark.parametrize(
        "mode, header",
        [
            (
                "developer",
                "username,start_date,end_date,commits,insertions,deletions,files,merges,repositories",
            ),
            (
                "repository",
                "repository,start_date,end_date,commits,insertions,deletions,files,merges,contributors",
            ),
        ],
    )
    def test_no_rows_still_prints_the_header(
        self, repofile, tmp_path, monkeypatch, capsys, mode, header
    ):
        argv = ["-u", "nobody", "-c", "-a", mode]
        assert self.run(monkeypatch, capsys, tmp_path, repofile, *argv) == header + "\n"
        out = self.run(monkeypatch, capsys, tmp_path, repofile, *argv, "-f", "json")
        assert json.loads(out) == []

    def test_invalid_mode_is_a_usage_error(
        self, repofile, tmp_path, monkeypatch, capsys
    ):
        with pytest.raises(SystemExit) as exc:
            self.run(monkeypatch, capsys, tmp_path, repofile, "-a", "team")
        assert exc.value.code == 2
        assert "invalid choice: 'team'" in capsys.readouterr().err

    def test_github_developer_and_repository(self, tmp_path, monkeypatch, capsys):
        widgets = Repo(tmp_path / "remotes" / "widgets")
        widgets.write("a.txt", lines(2))
        widgets.commit("ada", "work", email="ada@laptop.example")
        first = head(widgets)
        widgets.write("b.txt", lines(1))
        widgets.commit("Bob", "work", email="bob@example.com")
        local = Repo(tmp_path / "remotes" / "local")
        local.write("c.txt", lines(4))
        local.commit("Bob", "work", email="bob@home.example")
        local.write("d.txt", lines(1))
        local.commit("ada", "work", email="ada@laptop.example")
        github_world(
            tmp_path,
            monkeypatch,
            widgets,
            prs=[
                pr("adal99", at(2024, 3, 5), merged=at(2024, 3, 6)),
                pr("mia", at(2024, 3, 7)),
            ],
            users={"adal99": {"name": "Ada", "email": "ada@pub.example"}},
            contributors=["adal99"],
            linked={first: "adal99"},
            pushes=[push("adal99", at(2024, 3, 6))],
        )
        repofile = tmp_path / "repos.txt"
        repofile.write_text(f"{GITHUB_URL}\n{local.path}\n")
        argv = ["-rf", str(repofile), "--github", *DATES, "-f", "json", "-a"]
        out, _ = run_github(monkeypatch, capsys, tmp_path, *argv, "developer")
        rows = {(r["username"], r["github_username"]): r for r in json.loads(out)}
        # ada is matched on GitHub in widgets but not in the local repository;
        # mia, with no git row, sorts by her login
        assert list(rows) == [
            ("ada", "adal99"),
            ("ada", None),
            ("Bob", ""),
            ("", "mia"),
        ]
        ada = rows[("ada", "adal99")]
        assert (ada["commits"], ada["repositories"], ada["prs_opened"]) == (1, 1, 1)
        assert (ada["prs_merged"], ada["pushes_to_default"]) == (1, 1)
        assert (ada["git_email"], ada["github_email"]) == (
            "ada@laptop.example",
            "ada@pub.example",
        )
        unmatched = rows[("ada", None)]
        assert unmatched["commits"] == 1
        assert all(unmatched[c] is None for c in PR_COLUMNS + ACTIVITY_COLUMNS)
        # Bob: unmatched in widgets (zeros) and unavailable locally (empty)
        bob = rows[("Bob", "")]
        assert (bob["commits"], bob["repositories"], bob["prs_opened"]) == (2, 2, 0)
        assert (bob["git_email"], bob["github_email"]) == (
            "bob@example.com; bob@home.example",
            "",
        )
        assert rows[("", "mia")]["prs_opened"] == 1

        out, _ = run_github(monkeypatch, capsys, tmp_path, *argv, "repository")
        rows = json.loads(out)
        assert [(r["repository"], r["contributors"], r["commits"]) for r in rows] == [
            ("local", 2, 2),
            ("widgets", 3, 2),
        ]
        assert [rows[1][c] for c in PR_COLUMNS] == [2, 1, 0, 0]
        assert rows[1]["pushes_to_default"] == 1
        assert all(rows[0][c] is None for c in PR_COLUMNS + ACTIVITY_COLUMNS)
        assert not {"username", "github_username", "git_email", "github_email"} & set(
            rows[0]
        )
