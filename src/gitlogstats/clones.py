"""Deleting the repository clones a run used (REPO-5, --clobber)."""

import os
import shutil
import stat
import sys


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
