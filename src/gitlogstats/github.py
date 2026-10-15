"""
GitHub access for gitlogstats. Everything goes through the GitHub CLI (`gh`),
so the tool needs no token handling of its own. This module fetches pull
requests and turns them into per-GitHub-user counts; it prints nothing, so
callers decide what to show the user.
"""

import calendar
import datetime
import json
import re
import shutil
import subprocess

# CLI-3: the extra output columns
GITHUB_FIELDNAMES = [
    "github_username",
    "prs_opened",
    "prs_merged",
    "prs_closed_unmerged",
]

# CLI-3: the two user-facing messages, verbatim from the SPEC
GH_NOT_INSTALLED = (
    "gitlogstats: --github needs the GitHub CLI (gh), which is not installed. "
    "Install it from https://cli.github.com and run 'gh auth login', "
    "or run without --github."
)
GH_NOT_SIGNED_IN = (
    "gitlogstats: --github needs the GitHub CLI (gh) to be signed in. "
    "Run 'gh auth login', or run without --github."
)

# Login given to pull requests whose author's account was deleted
GHOST_LOGIN = "ghost"

_GITHUB_URL_PATTERNS = [
    # https://[user@]github.com/owner/repo, http://, www.
    re.compile(
        r"^https?://(?:[^/@]+@)?(?:www\.)?github\.com/"
        r"(?P<owner>[^/\s?#]+)/(?P<repo>[^/\s?#]+?)(?:\.git)?/?(?:[?#]\S*)?$",
        re.IGNORECASE,
    ),
    # git@github.com:owner/repo.git
    re.compile(
        r"^[^/@\s]+@github\.com:(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
        re.IGNORECASE,
    ),
    # ssh://git@github.com/owner/repo.git
    re.compile(
        r"^ssh://(?:[^/@]+@)?github\.com/"
        r"(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
        re.IGNORECASE,
    ),
]


class GitHubUnavailable(Exception):
    """gh is missing or not signed in; the message is shown to the user as is."""


class GitHubError(Exception):
    """A GitHub request failed for one repository (404, rate limit, network)."""


def check_gh():
    """
    CLI-3: check that gh is installed and signed in.
    @raises GitHubUnavailable: with the message to show the user
    """
    if shutil.which("gh") is None:
        raise GitHubUnavailable(GH_NOT_INSTALLED)
    result = subprocess.run(
        ["gh", "auth", "status"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0:
        raise GitHubUnavailable(GH_NOT_SIGNED_IN)


def github_repo_from_url(url):
    """
    Name the GitHub repository a clone URL points to.
    @param url: a repository URL or path
    @returns: "owner/repo" for github.com URLs, otherwise None
    """
    for pattern in _GITHUB_URL_PATTERNS:
        match = pattern.match(url.strip())
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    return None


def _parse_json_stream(text):
    """
    Parse text holding zero or more JSON documents back to back. Arrays are
    joined into one list; any other document is added as a single item.
    @param text: the output of gh api
    @returns: a list, or the lone document if the output is one non-array
    """
    decoder = json.JSONDecoder()
    documents = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        document, end = decoder.raw_decode(text, pos)
        documents.append(document)
        pos = end
        while pos < len(text) and text[pos].isspace():
            pos += 1
    if len(documents) == 1 and not isinstance(documents[0], list):
        return documents[0]
    merged = []
    for document in documents:
        if isinstance(document, list):
            merged.extend(document)
        else:
            merged.append(document)
    return merged


def gh_api(path, paginate=False):
    """
    Call the GitHub API through gh. With pagination, gh 2.83 merges the pages
    into one array while older versions print one array per page; both work.
    @param path: the API path, e.g. "repos/owner/repo/pulls"
    @param paginate: fetch every page
    @returns: the parsed JSON (an empty list for empty output)
    @raises GitHubError: if gh exits with an error; the message has gh's stderr
    """
    cmd = ["gh", "api", path]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or f"gh api {path} failed"
        raise GitHubError(message)
    try:
        return _parse_json_stream(result.stdout)
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        raise GitHubError(f"gh api {path} returned invalid JSON: {exc}")


def fetch_pull_requests(repo):
    """
    List every pull request of a repository, in any state.
    @param repo: "owner/repo"
    @returns: a list of dicts with login, user_type, state, created_at,
        merged_at, closed_at and base (the base branch name)
    @raises GitHubError: if the request fails
    """
    pulls = gh_api(f"repos/{repo}/pulls?state=all&per_page=100", paginate=True)
    result = []
    for pull in pulls:
        user = pull.get("user")
        result.append(
            {
                "login": user["login"] if user else GHOST_LOGIN,
                "user_type": user.get("type") if user else None,
                "state": pull.get("state"),
                "created_at": pull.get("created_at"),
                "merged_at": pull.get("merged_at"),
                "closed_at": pull.get("closed_at"),
                "base": (pull.get("base") or {}).get("ref"),
            }
        )
    return result


def _local_time(timestamp):
    """
    Convert a GitHub UTC timestamp ("2026-01-31T23:59:59Z") to local time.
    @param timestamp: the timestamp string, or None
    @returns: a naive local datetime, or None if there is no timestamp
    """
    if not timestamp:
        return None
    utc = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    return datetime.datetime.fromtimestamp(calendar.timegm(utc.timetuple()))


def count_pull_requests(prs, start, end, branch=None):
    """
    STAT-8, STAT-9, STAT-10: count each user's pull requests in a date range.
    The range is inclusive local time, as in FILT-1.
    @param prs: the list from fetch_pull_requests
    @param start: first day, mm/dd/yyyy
    @param end: last day, mm/dd/yyyy
    @param branch: count only pull requests with this base branch, if given
    @returns: {login: {"prs_opened", "prs_merged", "prs_closed_unmerged"}}
    """
    since = datetime.datetime.strptime(start, "%m/%d/%Y")
    until = datetime.datetime.strptime(end, "%m/%d/%Y").replace(
        hour=23, minute=59, second=59
    )

    def in_range(timestamp):
        moment = _local_time(timestamp)
        return moment is not None and since <= moment <= until

    counts = {}
    for pr in prs:
        if branch is not None and pr["base"] != branch:
            continue
        row = counts.setdefault(
            pr["login"],
            {"prs_opened": 0, "prs_merged": 0, "prs_closed_unmerged": 0},
        )
        if in_range(pr["created_at"]):
            row["prs_opened"] += 1
        if in_range(pr["merged_at"]):
            row["prs_merged"] += 1
        if (
            pr["state"] == "closed"
            and not pr["merged_at"]
            and in_range(pr["closed_at"])
        ):
            row["prs_closed_unmerged"] += 1
    return counts


def commit_login(repo, sha):
    """
    STAT-11: find the GitHub account GitHub links to a commit.
    @param repo: "owner/repo"
    @param sha: the commit hash
    @returns: the login, or None if GitHub links no account or does not have
        the commit (HTTP 404 or 422)
    @raises GitHubError: for any other failure (rate limit, network)
    """
    try:
        commit = gh_api(f"repos/{repo}/commits/{sha}")
    except GitHubError as exc:
        if "(HTTP 404)" in str(exc) or "(HTTP 422)" in str(exc):
            return None
        raise
    author = commit.get("author")
    return author.get("login") if author else None


def user_profile(login):
    """
    STAT-11: read a GitHub user's public profile.
    @param login: the GitHub username
    @returns: {"login", "name", "email"}; name and email may be None
    @raises GitHubError: if the request fails
    """
    user = gh_api(f"users/{login}")
    return {
        "login": user.get("login", login),
        "name": user.get("name"),
        "email": user.get("email"),
    }


def contributor_logins(repo):
    """
    STAT-11: list the accounts GitHub counts as contributors of a repository.
    @param repo: "owner/repo"
    @returns: a set of logins (empty for an empty repository)
    @raises GitHubError: if the request fails
    """
    contributors = gh_api(f"repos/{repo}/contributors?per_page=100", paginate=True)
    return {c["login"] for c in contributors if c.get("login")}
