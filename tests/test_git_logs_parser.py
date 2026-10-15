"""
Unit tests for GitLogsParser.
"""

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from gitlogstats import GitLogsParser

# ─── Shared test data ────────────────────────────────────────────────────────

SAMPLE_RESULTS = [
    {
        "username": "alice",
        "repository": "myrepo",
        "start_date": "01/01/2024",
        "end_date": "12/31/2024",
        "commits": 5,
        "insertions": 120,
        "deletions": 30,
        "files": 8,
    },
    {
        "username": "bob",
        "repository": "myrepo",
        "start_date": "01/01/2024",
        "end_date": "12/31/2024",
        "commits": 2,
        "insertions": 40,
        "deletions": 5,
        "files": 3,
    },
]

RS, FS = "\x1e", "\x1f"  # record and field separators used by GitLogsParser


def log_record(name, stat, sha="abc123", email=None):
    """One commit as printed by GitLogsParser.git_log_command()."""
    email = email or f"{name.lower()}@example.com"
    return f"{RS}{sha}{FS}{name}{FS}{email}\n" + (f"\n {stat}\n" if stat else "")


# git log --shortstat output: 2 commits, 3+1 files, 45+10 insertions, 12+2 deletions
GIT_LOG_TWO_COMMITS = log_record(
    "alice", "3 files changed, 45 insertions(+), 12 deletions(-)", "abc123def456"
) + log_record(
    "alice", "1 file changed, 10 insertions(+), 2 deletions(-)", "def456abc789"
)

# git log output with no deletions
GIT_LOG_INSERTIONS_ONLY = log_record("alice", "5 files changed, 100 insertions(+)")

GIT_LOG_EMPTY = ""


# ─── Helpers ─────────────────────────────────────────────────────────────────


def make_parser(**kwargs):
    """Return a GitLogsParser with os.chdir patched out."""
    defaults = {
        "repo": "/fake/repo",
        "start": "01/01/2024",
        "end": "12/31/2024",
        "username": None,
        "exclusions": [],
    }
    defaults.update(kwargs)
    with patch("os.chdir"):
        return GitLogsParser(**defaults)


def popen_mock(lines):
    """Return a patched subprocess.Popen class that yields *lines* from stdout."""
    instance = MagicMock()
    instance.stdout = iter(lines)
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=instance)


def run_mock(stdout_text):
    """Return a mock subprocess.run result with UTF-8-encoded *stdout_text*."""
    result = MagicMock()
    result.stdout = stdout_text.encode("utf-8")
    return result


# ─── repo_name_from_url ──────────────────────────────────────────────────────


class TestRepoNameFromUrl:
    def test_https_with_git_extension(self):
        assert (
            GitLogsParser.repo_name_from_url("https://github.com/user/my-repo.git")
            == "my-repo"
        )

    def test_https_without_extension(self):
        assert (
            GitLogsParser.repo_name_from_url("https://github.com/user/my-repo")
            == "my-repo"
        )

    def test_trailing_slash_stripped(self):
        assert (
            GitLogsParser.repo_name_from_url("https://github.com/user/my-repo/")
            == "my-repo"
        )

    def test_local_path(self):
        assert (
            GitLogsParser.repo_name_from_url("/home/user/projects/myrepo") == "myrepo"
        )

    def test_underscore_in_name(self):
        assert (
            GitLogsParser.repo_name_from_url("https://github.com/user/my_repo.git")
            == "my_repo"
        )

    def test_dot_in_name_is_kept(self):
        # git clone names the directory "repo.name", so the name must match it
        assert (
            GitLogsParser.repo_name_from_url("https://github.com/user/repo.name.git")
            == "repo.name"
        )

    def test_ssh_url_without_path(self):
        assert GitLogsParser.repo_name_from_url("git@host:my-repo.git") == "my-repo"

    def test_ssh_url(self):
        assert (
            GitLogsParser.repo_name_from_url("git@github.com:user/my-repo.git")
            == "my-repo"
        )


# ─── Constructor ─────────────────────────────────────────────────────────────


class TestConstructor:
    def test_stores_all_attributes(self):
        with patch("os.chdir"):
            p = GitLogsParser(
                repo="/some/path",
                start="01/01/2024",
                end="12/31/2024",
                username="alice",
                exclusions=["*.jpg"],
                repofile="/repos.txt",
                verbose=True,
                clean=True,
            )
        assert p.repository == "/some/path"
        assert p.start == "01/01/2024"
        assert p.end == "12/31/2024"
        assert p.username == "alice"
        assert p.exclusions == ["*.jpg"]
        assert p.repofile == "/repos.txt"
        assert p.verbose is True
        assert p.clean is True

    def test_chdir_called_with_repo_path(self):
        with patch("os.chdir") as mock_chdir:
            GitLogsParser(
                repo="/some/path", start="01/01/2024", end="12/31/2024", username=None
            )
        mock_chdir.assert_called_once_with("/some/path")

    def test_chdir_not_called_when_repo_is_none(self):
        with patch("os.chdir") as mock_chdir:
            GitLogsParser(
                repo=None, start="01/01/2024", end="12/31/2024", username=None
            )
        mock_chdir.assert_not_called()

    def test_default_values(self):
        with patch("os.chdir"):
            p = GitLogsParser(
                repo="/p", start="01/01/2024", end="12/31/2024", username=None
            )
        assert p.exclusions == []
        assert p.repofile is None
        assert p.verbose is False
        assert p.clean is False


# ─── verboseprint ─────────────────────────────────────────────────────────────


class TestVerboseprint:
    def test_prints_when_verbose_is_true(self, capsys):
        p = make_parser(verbose=True)
        p.verboseprint("hello verbose")
        assert "hello verbose" in capsys.readouterr().err

    def test_never_prints_to_stdout(self, capsys):
        # stdout carries the results (e.g. JSON); debugging info must not corrupt it
        p = make_parser(verbose=True)
        p.verboseprint("hello verbose")
        assert capsys.readouterr().out == ""

    def test_silent_when_verbose_is_false(self, capsys):
        p = make_parser(verbose=False)
        p.verboseprint("should not appear")
        assert capsys.readouterr() == ("", "")

    def test_multiple_args_all_printed(self, capsys):
        p = make_parser(verbose=True)
        p.verboseprint("x", "y", "z")
        out = capsys.readouterr().err
        assert "x" in out and "y" in out and "z" in out


# ─── format_results – CSV ─────────────────────────────────────────────────────


class TestFormatResultsCsv:
    def setup_method(self):
        self.p = make_parser()

    def test_header_row(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "csv").splitlines()
        expected = (
            "username,repository,start_date,end_date,commits,insertions,deletions,files"
        )
        assert lines[0] == expected

    def test_first_data_row(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "csv").splitlines()
        assert lines[1] == "alice,myrepo,01/01/2024,12/31/2024,5,120,30,8"

    def test_second_data_row(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "csv").splitlines()
        assert lines[2] == "bob,myrepo,01/01/2024,12/31/2024,2,40,5,3"

    def test_empty_results_returns_header_only(self):
        assert self.p.format_results([], "csv") == (
            "username,repository,start_date,end_date,commits,insertions,deletions,files\n"
        )

    def test_single_result_has_header_and_one_row(self):
        lines = [
            l
            for l in self.p.format_results([SAMPLE_RESULTS[0]], "csv").splitlines()
            if l
        ]
        assert len(lines) == 2


# ─── format_results – JSON ────────────────────────────────────────────────────


class TestFormatResultsJson:
    def setup_method(self):
        self.p = make_parser()

    def test_returns_valid_json(self):
        output = self.p.format_results(SAMPLE_RESULTS, "json")
        assert isinstance(json.loads(output), list)

    def test_correct_entry_count(self):
        output = self.p.format_results(SAMPLE_RESULTS, "json")
        assert len(json.loads(output)) == 2

    def test_field_values_preserved(self):
        parsed = json.loads(self.p.format_results(SAMPLE_RESULTS, "json"))
        assert parsed[0]["username"] == "alice"
        assert parsed[0]["commits"] == 5
        assert parsed[1]["username"] == "bob"

    def test_empty_results_returns_empty_array(self):
        assert json.loads(self.p.format_results([], "json")) == []


# ─── format_results – Markdown ───────────────────────────────────────────────


class TestFormatResultsMarkdown:
    def setup_method(self):
        self.p = make_parser()

    def test_header_row_present(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "markdown").splitlines()
        assert "username" in lines[0] and lines[0].startswith("|")

    def test_separator_row_present(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "markdown").splitlines()
        assert ":----" in lines[1]

    def test_data_rows_contain_usernames(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "markdown").splitlines()
        assert "alice" in lines[2]
        assert "bob" in lines[3]

    def test_all_rows_are_pipe_delimited(self):
        for line in self.p.format_results(SAMPLE_RESULTS, "markdown").splitlines():
            assert line.startswith("|") and line.endswith("|")

    def test_empty_results_returns_empty_string(self):
        assert self.p.format_results([], "markdown") == ""


# ─── format_results – unknown format ─────────────────────────────────────────


class TestFormatResultsUnknownFormat:
    def test_unknown_format_returns_empty_string(self):
        p = make_parser()
        assert p.format_results(SAMPLE_RESULTS, "xml") == ""


# ─── get_repository_urls ─────────────────────────────────────────────────────


class TestGetRepositoryUrls:
    def test_returns_single_repo_when_no_repofile(self):
        p = make_parser()
        assert p.get_repository_urls() == ["/fake/repo"]

    def test_reads_multiple_urls_from_repofile(self):
        content = (
            "https://github.com/user/repo1.git\nhttps://github.com/user/repo2.git\n"
        )
        p = make_parser(repofile="/repos.txt")
        with patch("builtins.open", mock_open(read_data=content)):
            urls = p.get_repository_urls()
        assert urls == [
            "https://github.com/user/repo1.git",
            "https://github.com/user/repo2.git",
        ]

    def test_repofile_with_single_url(self):
        content = "https://github.com/user/repo1.git\n"
        p = make_parser(repofile="/repos.txt")
        with patch("builtins.open", mock_open(read_data=content)):
            urls = p.get_repository_urls()
        assert urls == ["https://github.com/user/repo1.git"]


# ─── get_contributors ────────────────────────────────────────────────────────


class TestGetContributors:
    def test_returns_unique_contributors(self):
        p = make_parser()
        with patch(
            "subprocess.Popen", popen_mock(["Alice\n", "Bob\n", "Alice\n", "Carol\n"])
        ):
            contributors = p.get_contributors()
        assert set(contributors) == {"Alice", "Bob", "Carol"}

    def test_strips_whitespace_and_single_quotes(self):
        p = make_parser()
        with patch("subprocess.Popen", popen_mock(["'Alice'\n", "  Bob  \n"])):
            contributors = p.get_contributors()
        assert "Alice" in contributors
        assert "Bob" in contributors

    def test_empty_repo_returns_empty_list(self):
        p = make_parser()
        with patch("subprocess.Popen", popen_mock([])):
            assert p.get_contributors() == []

    def test_single_contributor(self):
        p = make_parser()
        with patch("subprocess.Popen", popen_mock(["Alice\n"])):
            assert p.get_contributors() == ["Alice"]

    def test_returns_list_type(self):
        p = make_parser()
        with patch("subprocess.Popen", popen_mock(["Alice\n", "Bob\n"])):
            assert isinstance(p.get_contributors(), list)


# ─── parse ───────────────────────────────────────────────────────────────────


class TestParse:
    def test_commits_counted(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            assert p.parse()[0]["commits"] == 2

    def test_insertions_summed(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            assert p.parse()[0]["insertions"] == 55  # 45 + 10

    def test_deletions_summed(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            assert p.parse()[0]["deletions"] == 14  # 12 + 2

    def test_files_summed(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            assert p.parse()[0]["files"] == 4  # 3 + 1

    def test_username_in_result(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            assert p.parse()[0]["username"] == "alice"

    def test_repository_name_extracted_from_url(self):
        p = make_parser(username="alice", repo="https://github.com/user/myrepo.git")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            assert p.parse()[0]["repository"] == "myrepo"

    def test_dates_preserved_in_result(self):
        p = make_parser(username="alice", start="03/01/2024", end="03/31/2024")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            entry = p.parse()[0]
        assert entry["start_date"] == "03/01/2024"
        assert entry["end_date"] == "03/31/2024"

    def test_empty_log_produces_zero_stats(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_EMPTY)):
            entry = p.parse()[0]
        assert entry["commits"] == 0
        assert entry["insertions"] == 0
        assert entry["deletions"] == 0
        assert entry["files"] == 0

    def test_insertions_only_no_deletions(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_INSERTIONS_ONLY)):
            entry = p.parse()[0]
        assert entry["insertions"] == 100
        assert entry["deletions"] == 0
        assert entry["files"] == 5

    def test_clean_true_removes_zero_activity_contributor(self):
        p = make_parser(username="alice", clean=True)
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_EMPTY)):
            assert p.parse() == []

    def test_clean_false_keeps_zero_activity_contributor(self):
        p = make_parser(username="alice", clean=False)
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_EMPTY)):
            assert len(p.parse()) == 1

    def test_all_contributors_used_when_no_username(self):
        p = make_parser(username=None)
        with patch("subprocess.Popen", popen_mock(["alice\n", "bob\n"])), patch(
            "subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)
        ):
            results = p.parse()
        assert len(results) == 2

    def test_result_contains_expected_keys(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            entry = p.parse()[0]
        expected_keys = {
            "username",
            "repository",
            "start_date",
            "end_date",
            "commits",
            "insertions",
            "deletions",
            "files",
        }
        assert set(entry.keys()) == expected_keys

    def test_single_commit_log(self):
        log = log_record("alice", "2 files changed, 20 insertions(+), 5 deletions(-)")
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(log)):
            entry = p.parse()[0]
        assert entry["commits"] == 1
        assert entry["insertions"] == 20
        assert entry["deletions"] == 5
        assert entry["files"] == 2


# ─── JSON output validity ─────────────────────────────────────────────────────


class TestJsonOutputValidity:
    def test_single_repo_is_valid_json(self):
        p = make_parser()
        output = p.format_results(SAMPLE_RESULTS, "json")
        parsed = json.loads(output)  # raises if invalid
        assert isinstance(parsed, list)

    def test_multi_repo_results_merged_into_single_array(self):
        repo1 = [SAMPLE_RESULTS[0]]
        repo2 = [SAMPLE_RESULTS[1]]
        p = make_parser()
        combined = p.format_results(repo1 + repo2, "json")
        parsed = json.loads(combined)
        assert len(parsed) == 2

    def test_concatenated_per_repo_json_is_invalid(self):
        # Demonstrates the bug that __main__.py previously had: printing one
        # json.dumps per repo produces two back-to-back arrays, not valid JSON.
        p = make_parser()
        bad_output = (
            p.format_results([SAMPLE_RESULTS[0]], "json")
            + "\n"
            + p.format_results([SAMPLE_RESULTS[1]], "json")
        )
        with pytest.raises(json.JSONDecodeError):
            json.loads(bad_output)


# ─── parse_log ───────────────────────────────────────────────────────────────


class TestParseLog:
    def test_empty_output_has_no_commits(self):
        assert GitLogsParser.parse_log("") == []

    def test_commit_without_stat_line_has_zero_stats(self):
        # merge commits and empty commits print no --shortstat line
        commits = GitLogsParser.parse_log(log_record("alice", None))
        assert commits == [
            {
                "hash": "abc123",
                "name": "alice",
                "email": "alice@example.com",
                "files": 0,
                "insertions": 0,
                "deletions": 0,
            }
        ]

    def test_deletions_only(self):
        commits = GitLogsParser.parse_log(
            log_record("alice", "1 file changed, 7 deletions(-)")
        )
        assert (
            commits[0]["files"],
            commits[0]["insertions"],
            commits[0]["deletions"],
        ) == (1, 0, 7)

    def test_singular_forms(self):
        commits = GitLogsParser.parse_log(
            log_record("alice", "1 file changed, 1 insertion(+), 1 deletion(-)")
        )
        assert (
            commits[0]["files"],
            commits[0]["insertions"],
            commits[0]["deletions"],
        ) == (1, 1, 1)

    def test_consecutive_commits_without_stats_do_not_borrow_stats(self):
        log = log_record("alice", None, "a1") + log_record(
            "bob", "2 files changed, 3 insertions(+)", "b1"
        )
        commits = GitLogsParser.parse_log(log)
        assert [c["files"] for c in commits] == [0, 2]
        assert [c["name"] for c in commits] == ["alice", "bob"]

    def test_names_and_emails_with_spaces_and_symbols(self):
        log = log_record(
            'Mary "M" O\'Neil-Smith (C++)',
            "1 file changed, 1 insertion(+)",
            email="m+o@example.com",
        )
        commit = GitLogsParser.parse_log(log)[0]
        assert commit["name"] == 'Mary "M" O\'Neil-Smith (C++)'
        assert commit["email"] == "m+o@example.com"

    def test_malformed_header_is_skipped(self):
        assert GitLogsParser.parse_log(f"{RS}garbage\n") == []


# ─── git_log_command ─────────────────────────────────────────────────────────


class TestGitLogCommand:
    def test_date_range_covers_whole_start_and_end_days(self):
        cmd = make_parser(start="03/01/2024", end="03/31/2024").git_log_command()
        assert "--since=2024-03-01 00:00:00" in cmd
        assert "--until=2024-03-31 23:59:59" in cmd

    def test_exclusions_become_pathspecs(self):
        cmd = make_parser(exclusions=["*.jpg", "", "foo.json"]).git_log_command()
        assert cmd[cmd.index("--") :] == [
            "--",
            ".",
            ":(exclude,glob)**/*.jpg",
            ":(exclude,glob)**/foo.json",
        ]

    def test_commit_messages_are_not_printed(self):
        # the format only prints hash, name and email; never %s or %b
        fmt = [a for a in make_parser().git_log_command() if a.startswith("--format=")][
            0
        ]
        assert "%s" not in fmt and "%b" not in fmt and "%B" not in fmt


# ─── parse: author matching ──────────────────────────────────────────────────


class TestParseAuthorMatching:
    LOG = (
        log_record("Al", "1 file changed, 1 insertion(+)", "a1", "al@example.com")
        + log_record(
            "Alice", "2 files changed, 20 insertions(+)", "a2", "alice@example.com"
        )
        + log_record(
            "Alice", "3 files changed, 30 insertions(+)", "a3", "alice@example.com"
        )
    )

    def test_name_that_is_a_prefix_of_another_is_not_merged(self):
        p = make_parser()
        with patch("subprocess.Popen", popen_mock(["Al\n", "Alice\n"])), patch(
            "subprocess.run", return_value=run_mock(self.LOG)
        ):
            by_name = {e["username"]: e for e in p.parse()}
        assert by_name["Al"]["commits"] == 1 and by_name["Al"]["insertions"] == 1
        assert by_name["Alice"]["commits"] == 2 and by_name["Alice"]["insertions"] == 50

    def test_username_option_matches_exact_name_only(self):
        p = make_parser(username="Al")
        with patch("subprocess.run", return_value=run_mock(self.LOG)):
            (entry,) = p.parse()
        assert entry["commits"] == 1

    def test_username_option_matches_email(self):
        p = make_parser(username="alice@example.com")
        with patch("subprocess.run", return_value=run_mock(self.LOG)):
            (entry,) = p.parse()
        assert entry["username"] == "alice@example.com"
        assert entry["commits"] == 2 and entry["files"] == 5

    def test_commit_by_unknown_author_is_ignored(self):
        p = make_parser()
        with patch("subprocess.Popen", popen_mock(["Al\n"])), patch(
            "subprocess.run", return_value=run_mock(self.LOG)
        ):
            (entry,) = p.parse()
        assert entry["username"] == "Al" and entry["commits"] == 1

    def test_clean_keeps_contributor_with_commits_but_no_line_changes(self):
        p = make_parser(username="alice", clean=True)
        with patch("subprocess.run", return_value=run_mock(log_record("alice", None))):
            (entry,) = p.parse()
        assert entry["commits"] == 1

    def test_non_utf8_output_does_not_crash(self):
        p = make_parser(username="alice")
        result = MagicMock()
        result.stdout = log_record("alice", "1 file changed").encode() + b"\xff"
        with patch("subprocess.run", return_value=result):
            assert p.parse()[0]["commits"] == 1


# ─── format_results: special characters ──────────────────────────────────────


class TestFormatResultsSpecialCharacters:
    ROW = [{**SAMPLE_RESULTS[0], "username": 'Smith, "Jo" | J'}]

    def test_csv_quotes_values_containing_commas_and_quotes(self):
        import csv as csvlib

        rows = list(
            csvlib.reader(make_parser().format_results(self.ROW, "csv").splitlines())
        )
        assert rows[1][0] == 'Smith, "Jo" | J'
        assert len(rows[1]) == len(rows[0])

    def test_markdown_escapes_pipes(self):
        line = make_parser().format_results(self.ROW, "markdown").splitlines()[2]
        assert 'Smith, "Jo" \\| J' in line


# ─── read_repository_urls ────────────────────────────────────────────────────


class TestReadRepositoryUrls:
    def test_ignores_blank_lines_comments_and_whitespace(self):
        text = "\n# course repos\n  https://a/x.git  \n\r\nhttps://a/y\n\n"
        assert GitLogsParser.read_repository_urls(text) == [
            "https://a/x.git",
            "https://a/y",
        ]
