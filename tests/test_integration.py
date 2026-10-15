"""
Integration tests: build real git repositories and check the statistics that
GitLogsParser and the gitlogstats command derive from them.
"""

import json
import os
import subprocess
import sys

import pytest

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

    def commit(self, author, message, date="2024-03-10 12:00:00", email=None, extra=()):
        """Stage everything and commit it as *author* on *date* (local time)."""
        email = email or f"{author.split()[0].lower()}@example.com"
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME=author,
            GIT_AUTHOR_EMAIL=email,
            GIT_COMMITTER_NAME=author,
            GIT_COMMITTER_EMAIL=email,
            GIT_AUTHOR_DATE=date,
            GIT_COMMITTER_DATE=date,
        )
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

    def test_merge_commit_counts_as_commit_without_duplicating_stats(
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
        assert counts(result["Alice"]) == (3, 2, 3, 0)  # base + main work + merge
        assert counts(result["Bob"]) == (1, 1, 4, 0)

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
            == "username,repository,start_date,end_date,commits,insertions,deletions,files"
        )
        assert "Alice,one,01/01/2024,12/31/2024,1,3,0,1" in rows
        assert "Bob,one,01/01/2024,12/31/2024,1,1,0,1" in rows

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
            "username,repository,start_date,end_date,commits,insertions,deletions,files\n"
            '"Dana ""DJ"" Jones",alpha,01/01/2024,12/31/2024,1,2,0,1\n'
            '"Smith, Jo",alpha,01/01/2024,12/31/2024,1,3,0,1\n'
        )

    def test_multiple_repositories_csv(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(monkeypatch, capsys, tmp_path, "-rf", str(remotes[2]))
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,files\n"
            '"Dana ""DJ"" Jones",alpha,01/01/2024,12/31/2024,1,2,0,1\n'
            '"Smith, Jo",alpha,01/01/2024,12/31/2024,1,3,0,1\n'
            '"Smith, Jo",beta.repo,01/01/2024,12/31/2024,1,4,0,1\n'
        )

    def test_empty_csv_is_header_only(self, remotes, tmp_path, monkeypatch, capsys):
        out = self.run(
            monkeypatch, capsys, tmp_path, "-rf", str(remotes[2]), "-u", "X", "-c"
        )
        assert out == (
            "username,repository,start_date,end_date,commits,insertions,deletions,files\n"
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
