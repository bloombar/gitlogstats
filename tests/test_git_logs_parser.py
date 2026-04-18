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

# git log --shortstat output: 2 commits, 3+1 files, 45+10 insertions, 12+2 deletions
GIT_LOG_TWO_COMMITS = (
    "commit abc123def456\n"
    "Author: alice <alice@example.com>\n"
    "Date:   Mon Jan 15 12:00:00 2024 -0500\n"
    "\n"
    "    Added new feature\n"
    "\n"
    " 3 files changed, 45 insertions(+), 12 deletions(-)\n"
    "\n"
    "commit def456abc789\n"
    "Author: alice <alice@example.com>\n"
    "Date:   Tue Jan 16 09:30:00 2024 -0500\n"
    "\n"
    "    Fixed bug\n"
    "\n"
    " 1 file changed, 10 insertions(+), 2 deletions(-)\n"
)

# git log output with no deletions line
GIT_LOG_INSERTIONS_ONLY = (
    "commit abc123def456\n"
    "Author: alice <alice@example.com>\n"
    "Date:   Mon Jan 15 12:00:00 2024 -0500\n"
    "\n"
    "    Initial commit\n"
    "\n"
    " 5 files changed, 100 insertions(+)\n"
)

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
        assert GitLogsParser.repo_name_from_url("https://github.com/user/my-repo.git") == "my-repo"

    def test_https_without_extension(self):
        assert GitLogsParser.repo_name_from_url("https://github.com/user/my-repo") == "my-repo"

    def test_trailing_slash_stripped(self):
        assert GitLogsParser.repo_name_from_url("https://github.com/user/my-repo/") == "my-repo"

    def test_local_path(self):
        assert GitLogsParser.repo_name_from_url("/home/user/projects/myrepo") == "myrepo"

    def test_underscore_in_name(self):
        assert GitLogsParser.repo_name_from_url("https://github.com/user/my_repo.git") == "my_repo"

    def test_dot_in_name_returns_first_segment(self):
        # repo.name.git → "repo" (split on "." takes index 0)
        assert GitLogsParser.repo_name_from_url("https://github.com/user/repo.name.git") == "repo"

    def test_ssh_url(self):
        assert GitLogsParser.repo_name_from_url("git@github.com:user/my-repo.git") == "my-repo"


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
            GitLogsParser(repo="/some/path", start="01/01/2024", end="12/31/2024", username=None)
        mock_chdir.assert_called_once_with("/some/path")

    def test_chdir_not_called_when_repo_is_none(self):
        with patch("os.chdir") as mock_chdir:
            GitLogsParser(repo=None, start="01/01/2024", end="12/31/2024", username=None)
        mock_chdir.assert_not_called()

    def test_default_values(self):
        with patch("os.chdir"):
            p = GitLogsParser(repo="/p", start="01/01/2024", end="12/31/2024", username=None)
        assert p.exclusions == []
        assert p.repofile is None
        assert p.verbose is False
        assert p.clean is False


# ─── verboseprint ─────────────────────────────────────────────────────────────

class TestVerboseprint:
    def test_prints_when_verbose_is_true(self, capsys):
        p = make_parser(verbose=True)
        p.verboseprint("hello verbose")
        assert "hello verbose" in capsys.readouterr().out

    def test_silent_when_verbose_is_false(self, capsys):
        p = make_parser(verbose=False)
        p.verboseprint("should not appear")
        assert capsys.readouterr().out == ""

    def test_multiple_args_all_printed(self, capsys):
        p = make_parser(verbose=True)
        p.verboseprint("x", "y", "z")
        out = capsys.readouterr().out
        assert "x" in out and "y" in out and "z" in out


# ─── format_results – CSV ─────────────────────────────────────────────────────

class TestFormatResultsCsv:
    def setup_method(self):
        self.p = make_parser()

    def test_header_row(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "csv").splitlines()
        expected = "username,repository,start_date,end_date,commits,insertions,deletions,files"
        assert lines[0] == expected

    def test_first_data_row(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "csv").splitlines()
        assert lines[1] == "alice,myrepo,01/01/2024,12/31/2024,5,120,30,8"

    def test_second_data_row(self):
        lines = self.p.format_results(SAMPLE_RESULTS, "csv").splitlines()
        assert lines[2] == "bob,myrepo,01/01/2024,12/31/2024,2,40,5,3"

    def test_empty_results_returns_empty_string(self):
        assert self.p.format_results([], "csv") == ""

    def test_single_result_has_header_and_one_row(self):
        lines = [l for l in self.p.format_results([SAMPLE_RESULTS[0]], "csv").splitlines() if l]
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
        content = "https://github.com/user/repo1.git\nhttps://github.com/user/repo2.git\n"
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
        with patch("subprocess.Popen", popen_mock(["Alice\n", "Bob\n", "Alice\n", "Carol\n"])):
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
        with patch("subprocess.Popen", popen_mock(["alice\n", "bob\n"])), \
             patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            results = p.parse()
        assert len(results) == 2

    def test_result_contains_expected_keys(self):
        p = make_parser(username="alice")
        with patch("subprocess.run", return_value=run_mock(GIT_LOG_TWO_COMMITS)):
            entry = p.parse()[0]
        expected_keys = {"username", "repository", "start_date", "end_date",
                         "commits", "insertions", "deletions", "files"}
        assert set(entry.keys()) == expected_keys

    def test_single_commit_log(self):
        log = (
            "commit abc123def456\n"
            "Author: alice <alice@example.com>\n"
            "Date:   Mon Jan 15 12:00:00 2024 -0500\n"
            "\n"
            "    Solo commit\n"
            "\n"
            " 2 files changed, 20 insertions(+), 5 deletions(-)\n"
        )
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
