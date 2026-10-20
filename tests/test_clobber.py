"""Tests for --clobber (REPO-5): deleting the clones a run used."""

import json
import os
import stat
import sys

import pytest

from gitlogstats import clones
from gitlogstats.__main__ import main
from gitlogstats.clones import remove_clones
from test_integration import (
    DATES,
    GITHUB_URL,
    Repo,
    github_world,
    lines,
    pr,
    run_github,
)


@pytest.fixture
def remotes(tmp_path):
    """Two 'remote' repositories that the command clones by path."""
    one = Repo(tmp_path / "remotes" / "one")
    one.write("a.txt", lines(3))
    one.commit("Alice", "one: add")
    two = Repo(tmp_path / "remotes" / "two.repo")
    two.write("c.txt", lines(2))
    two.commit("Alice", "two: add")
    return one, two


@pytest.fixture
def work(tmp_path):
    path = tmp_path / "work"
    path.mkdir()
    return path


def run(monkeypatch, capsys, work, *argv):
    """Run the command in *work*; returns (stdout, stderr)."""
    monkeypatch.chdir(work)
    monkeypatch.setattr(
        sys, "argv", ["gitlogstats", *argv, "-s", "01/01/2024"] + ["-e", "12/31/2024"]
    )
    main()
    captured = capsys.readouterr()
    return captured.out, captured.err


class TestCommand:
    def test_clones_are_kept_without_the_flag(self, remotes, work, monkeypatch, capsys):
        run(monkeypatch, capsys, work, "-r", remotes[0].path)
        assert (work / "repos" / "one" / ".git").is_dir()

    def test_clobber_prints_the_same_results_and_removes_everything(
        self, remotes, work, monkeypatch, capsys
    ):
        kept, _ = run(monkeypatch, capsys, work, "-r", remotes[0].path, "-f", "json")
        assert (work / "repos").exists()
        # a fresh directory so that the second run clones again
        other = work.parent / "work2"
        other.mkdir()
        out, err = run(
            monkeypatch, capsys, other, "-r", remotes[0].path, "-f", "json", "--clobber"
        )
        assert out == kept and json.loads(out)[0]["commits"] == 1
        assert err == ""
        assert os.listdir(other) == []  # repos/ itself is gone

    def test_other_clones_and_repos_dir_are_kept(
        self, remotes, work, monkeypatch, capsys
    ):
        run(monkeypatch, capsys, work, "-r", remotes[1].path)
        out, _ = run(monkeypatch, capsys, work, "-r", remotes[0].path, "--clobber")
        assert "Alice,one," in out
        assert sorted(os.listdir(work / "repos")) == ["two.repo"]

    def test_repofile_with_two_repos_and_a_duplicate(
        self, remotes, work, monkeypatch, capsys
    ):
        repofile = work.parent / "list.txt"
        repofile.write_text(
            f"{remotes[0].path}\n{remotes[1].path}\n{remotes[0].path}\n"
        )
        out, _ = run(monkeypatch, capsys, work, "-rf", str(repofile), "--clobber")
        assert "Alice,one," in out and "Alice,two.repo," in out
        assert os.listdir(work) == []

    def test_failure_before_output_deletes_nothing(
        self, remotes, work, monkeypatch, capsys
    ):
        repofile = work.parent / "list.txt"
        repofile.write_text(f"{remotes[0].path}\n{work.parent / 'missing'}\n")
        with pytest.raises(Exception):
            run(monkeypatch, capsys, work, "-rf", str(repofile), "--clobber")
        assert (work / "repos" / "one" / ".git").is_dir()
        assert capsys.readouterr().out == ""

    def test_verbose_lists_deleted_paths_on_stderr_only(
        self, remotes, work, monkeypatch, capsys
    ):
        quiet, _ = run(monkeypatch, capsys, work, "-r", remotes[0].path, "--clobber")
        out, err = run(
            monkeypatch, capsys, work, "-r", remotes[0].path, "--clobber", "-v"
        )
        assert out == quiet
        repos = os.path.realpath(work / "repos")
        assert f"gitlogstats: deleted {os.path.join(repos, 'one')}" in err
        assert f"gitlogstats: deleted {repos}\n" in err
        assert "deleted" not in out

    def test_clobber_with_github(self, remotes, tmp_path, monkeypatch, capsys):
        github_world(tmp_path, monkeypatch, remotes[0], prs=[], contributors=[])
        out, _ = run_github(
            monkeypatch,
            capsys,
            tmp_path,
            "-r",
            GITHUB_URL,
            "--github",
            *DATES,
            "--clobber",
        )
        assert "Alice" in out
        assert not (tmp_path / "work" / "repos").exists()

    def test_nothing_to_delete_when_no_repositories(self, work, monkeypatch, capsys):
        repofile = work.parent / "empty.txt"
        repofile.write_text("# nothing\n")
        out, _ = run(monkeypatch, capsys, work, "-rf", str(repofile), "--clobber")
        assert out == "" and os.listdir(work) == []


class TestRemoveClones:
    def test_read_only_files_are_deleted(self, tmp_path):
        repos = tmp_path / "repos"
        clone = repos / "x"
        (clone / "objects").mkdir(parents=True)
        for name in ("a", "objects/pack"):
            (clone / name).write_text("data")
            os.chmod(clone / name, stat.S_IREAD)
        os.chmod(clone / "objects", stat.S_IREAD | stat.S_IEXEC)
        remove_clones(str(repos), [str(clone)])
        assert not repos.exists()

    def test_symlink_is_unlinked_and_target_untouched(self, tmp_path):
        target = tmp_path / "precious"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        repos = tmp_path / "repos"
        repos.mkdir()
        os.symlink(target, repos / "link")
        remove_clones(str(repos), [str(repos / "link")])
        assert not repos.exists()
        assert (target / "keep.txt").read_text() == "keep"

    def test_paths_outside_repos_are_skipped(self, tmp_path, capsys):
        repos = tmp_path / "repos"
        repos.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        nested = repos / "a" / "b"
        nested.mkdir(parents=True)
        for path in (outside, repos / ".." / "outside", nested, repos):
            remove_clones(str(repos), [str(path)], verbose=True)
        assert outside.is_dir() and nested.is_dir() and repos.is_dir()
        assert capsys.readouterr().err.count("not deleting") == 4

    def test_skipped_paths_are_silent_without_verbose(self, tmp_path, capsys):
        repos = tmp_path / "repos"
        repos.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        remove_clones(str(repos), [str(outside)])
        assert outside.is_dir() and capsys.readouterr().err == ""

    def test_a_file_in_place_of_a_clone_is_removed(self, tmp_path):
        repos = tmp_path / "repos"
        repos.mkdir()
        (repos / "f").write_text("x")
        remove_clones(str(repos), [str(repos / "f")])
        assert not repos.exists()

    def test_deletion_error_is_reported_and_the_rest_continues(
        self, tmp_path, monkeypatch, capsys
    ):
        repos = tmp_path / "repos"
        for name in ("bad", "good"):
            (repos / name).mkdir(parents=True)

        real = clones._delete

        def flaky(path):
            if path.endswith("bad"):
                raise PermissionError(13, "Permission denied")
            real(path)

        monkeypatch.setattr(clones, "_delete", flaky)
        remove_clones(str(repos), [str(repos / "bad"), str(repos / "good")])
        err = capsys.readouterr().err
        assert (
            f"gitlogstats: could not delete {repos / 'bad'}: Permission denied" in err
        )
        assert os.listdir(repos) == ["bad"]

    @pytest.mark.skipif(
        sys.platform == "win32" or os.geteuid() == 0,
        reason="needs POSIX permissions that apply to the current user",
    )
    def test_unreadable_folder_is_reported_and_the_rest_continues(
        self, tmp_path, capsys
    ):
        # a folder that cannot be opened makes rmtree call the handler with
        # os.open; retrying that must not crash after the results are printed
        repos = tmp_path / "repos"
        locked = repos / "one" / "notes" / "private"
        locked.mkdir(parents=True)
        (locked / "a.txt").write_text("x")
        (repos / "two").mkdir()
        locked.chmod(0)
        try:
            remove_clones(str(repos), [str(repos / "one"), str(repos / "two")])
        finally:
            locked.chmod(stat.S_IRWXU)
        err = capsys.readouterr().err
        assert f"gitlogstats: could not delete {repos / 'one'}" in err
        assert not (repos / "two").exists()

    def test_other_errors_while_deleting_are_not_retried(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            clones._make_writable_and_retry(
                os.remove, str(tmp_path / "gone"), (None, FileNotFoundError(), None)
            )

    def test_retry_gives_up_when_chmod_is_impossible(self, tmp_path):
        # the paths do not exist, so chmod fails quietly and the retry raises
        with pytest.raises(FileNotFoundError):
            clones._make_writable_and_retry(
                os.remove,
                str(tmp_path / "no" / "gone"),
                (None, PermissionError(), None),
            )

    def test_a_clone_that_is_already_gone_is_not_an_error(self, tmp_path, capsys):
        repos = tmp_path / "repos"
        repos.mkdir()
        remove_clones(str(repos), [str(repos / "gone")], verbose=True)
        assert capsys.readouterr().err == f"gitlogstats: deleted {repos}\n"


class TestSameRemote:
    """REPO-6: whether a clone was made from the repository given."""

    def test_equal_urls(self, tmp_path):
        url = "https://github.com/alice/proj.git"
        assert clones.same_remote(url, url, str(tmp_path))

    def test_forks_with_the_same_name_differ(self, tmp_path):
        assert not clones.same_remote(
            "https://github.com/alice/proj.git",
            "https://github.com/bob/proj.git",
            str(tmp_path),
        )

    def test_local_paths_are_compared_by_folder(self, tmp_path):
        (tmp_path / "proj").mkdir()
        repos = tmp_path / "repos"
        repos.mkdir()
        recorded = str(repos / ".." / "proj")  # as git records "../proj"
        assert clones.same_remote(recorded, "../proj", str(repos))
        assert clones.same_remote(recorded, str(tmp_path / "proj") + "/", str(repos))
        assert not clones.same_remote(recorded, str(repos), str(repos))

    def test_a_missing_path_matches_only_itself(self, tmp_path):
        assert not clones.same_remote(
            str(tmp_path / "gone"), str(tmp_path / "other"), str(tmp_path)
        )
