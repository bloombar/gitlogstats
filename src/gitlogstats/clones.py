"""Choosing the folder for each repository's clone (REPO-3, REPO-6) and
deleting the clones a run used (REPO-5, --clobber)."""

import os
import shutil
import stat
import subprocess
import sys


def origin_url(clone_dir):
    """
    Read the URL a clone was cloned from.
    @param clone_dir: a folder that may hold a clone
    @returns: the clone's origin URL, or None if the folder is not a clone of
        its own (no .git inside, so git would look in a parent folder) or has
        no origin
    """
    if not os.path.isdir(os.path.join(clone_dir, ".git")):
        return None
    # the URL as recorded by git clone; `git remote get-url` would apply any
    # url.<base>.insteadOf rewrite, so a reused clone would never match
    result = subprocess.run(
        ["git", "-C", clone_dir, "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def same_remote(origin, repo_url, repos_dir):
    """
    REPO-6: whether a clone's origin is the repository given on the command
    line. URLs must be equal. git records a local path made absolute, from
    repos_dir (where clones are made), so local paths are compared by the
    folder they lead to.
    @param origin: the clone's origin URL, from origin_url
    @param repo_url: the repository as given on the command line
    @param repos_dir: the folder clones are made from
    @returns: a bool
    """
    if origin == repo_url:
        return True
    local = os.path.join(repos_dir, repo_url)  # an absolute path stays as is
    if os.path.exists(origin) and os.path.exists(local):
        return _work_tree(origin) == _work_tree(local)
    return False


def _work_tree(path):
    """
    The folder a local repository path leads to, the same for `proj` and
    `proj/.git`.
    @param path: an existing local path
    @returns: its real path, without a final .git folder
    """
    real = os.path.realpath(path)
    return os.path.dirname(real) if os.path.basename(real) == ".git" else real


def clone_dir_for(repos_dir, name, repo_url):
    """
    REPO-3, REPO-6: choose the folder in repos_dir for a repository's clone:
    repos_dir/name, or name-2, name-3, ... when a different repository with
    the same name already has that folder.
    @param repos_dir: the folder that holds the clones
    @param name: the repository's name, as git clone names its folder
    @param repo_url: the repository as given on the command line
    @returns: (path, whether a clone of this repository is already there)
    """
    number = 1
    while True:
        path = os.path.join(repos_dir, name if number == 1 else f"{name}-{number}")
        if not os.path.lexists(path):
            return path, False
        origin = origin_url(path)
        if origin is not None and same_remote(origin, repo_url, repos_dir):
            return path, True
        number += 1


def _make_writable_and_retry(function, path, exc_info):
    """
    Error handler for shutil.rmtree: git marks some files read-only (notably
    pack files on Windows), which stops them being deleted. Clear the read-only
    bit on the file and its folder, then try again. Any other error is raised,
    as is a failure to open or list a folder: retrying os.open or os.scandir
    with only a path would itself fail with a TypeError.
    """
    if not isinstance(exc_info[1], PermissionError) or function not in (
        os.unlink,
        os.remove,
        os.rmdir,
    ):
        raise exc_info[1]
    for target in (os.path.dirname(path), path):
        try:
            os.chmod(target, os.stat(target).st_mode | stat.S_IRWXU)
        except OSError:
            pass
    function(path)


def _delete(path):
    """
    Delete one clone. A symbolic link is unlinked, never followed.
    @param path: the clone's path
    """
    if os.path.islink(path) or not os.path.isdir(path):
        os.remove(path)
    else:
        shutil.rmtree(path, onerror=_make_writable_and_retry)


def remove_clones(repos_dir, clone_dirs, verbose=False):
    """
    Delete the given clones, then remove repos_dir if nothing else is left in it.
    Only direct children of repos_dir are deleted; any other path is skipped.
    A failed deletion is reported on standard error and does not stop the rest.
    @param repos_dir: the directory holding the clones
    @param clone_dirs: the paths of the clones to delete (duplicates are fine)
    @param verbose: whether to report each deleted or skipped path on stderr
    """
    real_repos = os.path.realpath(repos_dir)
    seen = set()
    for clone_dir in clone_dirs:
        path = os.path.normpath(os.path.abspath(clone_dir))
        if path in seen:
            continue
        seen.add(path)
        # the folder that holds the clone must be repos_dir itself; checking the
        # parent (not the path) means a symbolic link is judged by where it sits
        if os.path.realpath(os.path.dirname(path)) != real_repos:
            if verbose:
                print(
                    f"gitlogstats: not deleting {path}: not inside {repos_dir}",
                    file=sys.stderr,
                )
            continue
        if not os.path.lexists(path):
            continue
        try:
            _delete(path)
        except OSError as exc:
            print(
                f"gitlogstats: could not delete {path}: {exc.strerror or exc}",
                file=sys.stderr,
            )
            continue
        if verbose:
            print(f"gitlogstats: deleted {path}", file=sys.stderr)

    try:
        os.rmdir(repos_dir)  # only succeeds when empty
    except OSError:
        return
    if verbose:
        print(f"gitlogstats: deleted {repos_dir}", file=sys.stderr)
