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
import urllib.parse

# CLI-3: the extra output columns
GITHUB_FIELDNAMES = [
    "github_username",
    "prs_opened",
    "prs_merged",
    "prs_closed_unmerged",
    "prs_self_merged",
]

# STAT-13: the email columns that follow the pull-request columns
EMAIL_FIELDNAMES = ["git_email", "github_email"]

# STAT-14, STAT-15: the activity columns that follow the email columns
ACTIVITY_FIELDNAMES = ["pushes_to_default", "web_commits"]

# STAT-14: the activity types that are a person pushing to a branch
PUSH_TYPES = ("push", "force_push")

# STAT-15: the committer GitHub records for commits it creates itself
GITHUB_COMMITTER_EMAIL = "noreply@github.com"

# STAT-15: how many seconds a commit's committer time may differ from a pull
# request's merge commit and still be part of that pull request's merge
MERGE_TIME_TOLERANCE = 2

# STAT-15: GitHub commits a merge result seconds before it stamps the pull
# request merged; a "merge commit" much older than the merge is the pull
# request's own head commit, which reached the branch another way, so that
# merge created no commit
MERGE_COMMIT_LAG = 60

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

# STAT-12: the list endpoint of the REST API does not say who merged a pull
# request, but GraphQL does, in one paginated query (gh fills in $endCursor)
PULLS_QUERY = (
    "query($owner:String!,$name:String!,$endCursor:String){"
    "repository(owner:$owner,name:$name){"
    "pullRequests(first:100,after:$endCursor){"
    "pageInfo{hasNextPage endCursor} "
    "nodes{author{login __typename} mergedBy{login __typename} "
    "state createdAt mergedAt closedAt baseRefName "
    "mergeCommit{oid committedDate}}}}}"
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


def gh_graphql(query, variables):
    """
    Run a paginated GraphQL query through gh. gh prints one JSON document per
    page, back to back.
    @param query: the query text; it must use $endCursor for pagination
    @param variables: {name: string value}, passed as separate arguments
    @returns: a list with one parsed response per page
    @raises GitHubError: if gh exits with an error or the response has errors
    """
    cmd = ["gh", "api", "graphql", "--paginate", "-f", f"query={query}"]
    for name, value in variables.items():
        # -f sends a raw string; -F would turn "2048" or "true" into a number
        # or boolean, which GitHub rejects for String! variables
        cmd += ["-f", f"{name}={value}"]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0:
        raise GitHubError(result.stderr.strip() or "gh api graphql failed")
    try:
        pages = _parse_json_stream(result.stdout)
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        raise GitHubError(f"gh api graphql returned invalid JSON: {exc}")
    if isinstance(pages, dict):
        pages = [pages]
    for page in pages:
        if page.get("errors"):
            messages = [e.get("message", "unknown error") for e in page["errors"]]
            raise GitHubError("; ".join(messages))
    return pages


def _graphql_login(account):
    """
    Read a login from a GraphQL author or merger. GraphQL leaves "[bot]" off
    bot logins that the REST API includes, so it is added back.
    @param account: {"login", "__typename"}, or None for a deleted account
    @returns: the login, or None if there is no account
    """
    if not account:
        return None
    login = account["login"]
    return login + "[bot]" if account.get("__typename") == "Bot" else login


def fetch_pull_requests(repo):
    """
    List every pull request of a repository, in any state.
    @param repo: "owner/repo"
    @returns: a list of dicts with login, user_type, state ("open" or
        "closed"), created_at, merged_at, closed_at, base (the base branch
        name), merged_by (a login, or None if not merged or unknown),
        merge_commit (the hash of the commit that merged it, or None) and
        merge_committed_at (that commit's committer time, or None)
    @raises GitHubError: if the request fails
    """
    owner, name = repo.split("/", 1)
    pages = gh_graphql(PULLS_QUERY, {"owner": owner, "name": name})
    result = []
    for page in pages:
        repository = (page.get("data") or {}).get("repository")
        if repository is None:
            raise GitHubError(f"could not read pull requests of {repo}")
        for pull in repository["pullRequests"]["nodes"]:
            author = pull.get("author")
            merge_commit = pull.get("mergeCommit") or {}
            result.append(
                {
                    "login": _graphql_login(author) or GHOST_LOGIN,
                    "user_type": author.get("__typename") if author else None,
                    "state": "open" if pull.get("state") == "OPEN" else "closed",
                    "created_at": pull.get("createdAt"),
                    "merged_at": pull.get("mergedAt"),
                    "closed_at": pull.get("closedAt"),
                    "base": pull.get("baseRefName"),
                    "merged_by": _graphql_login(pull.get("mergedBy")),
                    "merge_commit": merge_commit.get("oid"),
                    "merge_committed_at": merge_commit.get("committedDate"),
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


def _range_test(start, end):
    """
    Build a test for whether a GitHub timestamp falls in the date range. The
    range is inclusive local time, as in FILT-1.
    @param start: first day, mm/dd/yyyy
    @param end: last day, mm/dd/yyyy
    @returns: a function taking a timestamp (or None) and returning a bool
    """
    since = datetime.datetime.strptime(start, "%m/%d/%Y")
    until = datetime.datetime.strptime(end, "%m/%d/%Y").replace(
        hour=23, minute=59, second=59
    )

    def in_range(timestamp):
        moment = _local_time(timestamp)
        return moment is not None and since <= moment <= until

    return in_range


def local_day(moment):
    """
    OUT-7: the local day of a moment, as git reports a commit's day.
    @param moment: a GitHub UTC timestamp string, or seconds since the epoch
    @returns: the day as mm/dd/yyyy
    """
    if isinstance(moment, str):
        moment = _local_time(moment)
    else:
        moment = datetime.datetime.fromtimestamp(moment)
    return moment.strftime("%m/%d/%Y")


def event_days(prs, pushes, start, end):
    """
    OUT-7: the days in a date range on which a pull request was opened,
    merged or closed, or a push was made.
    @param prs: the list from fetch_pull_requests
    @param pushes: the list from fetch_pushes
    @param start: first day, mm/dd/yyyy
    @param end: last day, mm/dd/yyyy
    @returns: a set of days, mm/dd/yyyy
    """
    in_range = _range_test(start, end)
    moments = [push["timestamp"] for push in pushes]
    for pr in prs:
        moments += [pr["created_at"], pr["merged_at"], pr["closed_at"]]
    return {local_day(moment) for moment in moments if in_range(moment)}


def count_pull_requests(prs, start, end, branch=None):
    """
    STAT-8, STAT-9, STAT-10, STAT-12: count each user's pull requests in a date range.
    The range is inclusive local time, as in FILT-1.
    @param prs: the list from fetch_pull_requests
    @param start: first day, mm/dd/yyyy
    @param end: last day, mm/dd/yyyy
    @param branch: count only pull requests with this base branch, if given
    @returns: {login: {"prs_opened", "prs_merged", "prs_closed_unmerged",
        "prs_self_merged"}}
    """
    in_range = _range_test(start, end)

    counts = {}
    for pr in prs:
        if branch is not None and pr["base"] != branch:
            continue
        row = counts.setdefault(
            pr["login"],
            {
                "prs_opened": 0,
                "prs_merged": 0,
                "prs_closed_unmerged": 0,
                "prs_self_merged": 0,
            },
        )
        if in_range(pr["created_at"]):
            row["prs_opened"] += 1
        if in_range(pr["merged_at"]):
            row["prs_merged"] += 1
            # STAT-12: the merger is the author; an unknown merger never is
            merger = pr.get("merged_by")
            if merger and merger.casefold() == pr["login"].casefold():
                row["prs_self_merged"] += 1
        if (
            pr["state"] == "closed"
            and not pr["merged_at"]
            and in_range(pr["closed_at"])
        ):
            row["prs_closed_unmerged"] += 1
    return counts


def fetch_pushes(repo, branch):
    """
    STAT-14: list the pushes to one branch from GitHub's activity record.
    @param repo: "owner/repo"
    @param branch: the branch name, e.g. "main"
    @returns: a list of {"login", "timestamp"}, one per push or force push;
        the login of a deleted account is GHOST_LOGIN
    @raises GitHubError: if the request fails
    """
    ref = urllib.parse.quote(f"refs/heads/{branch}", safe="/")
    activity = gh_api(f"repos/{repo}/activity?per_page=100&ref={ref}", paginate=True)
    return [
        {
            "login": (item.get("actor") or {}).get("login") or GHOST_LOGIN,
            "timestamp": item.get("timestamp"),
        }
        for item in activity
        if item.get("activity_type") in PUSH_TYPES
    ]


def count_pushes(pushes, start, end):
    """
    STAT-14: count each user's pushes in a date range (inclusive local time).
    @param pushes: the list from fetch_pushes
    @param start: first day, mm/dd/yyyy
    @param end: last day, mm/dd/yyyy
    @returns: {login: number of pushes}
    """
    in_range = _range_test(start, end)
    counts = {}
    for push in pushes:
        if in_range(push["timestamp"]):
            counts[push["login"]] = counts.get(push["login"], 0) + 1
    return counts


def _utc_seconds(timestamp):
    """Convert a GitHub UTC timestamp to seconds since the epoch."""
    utc = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    return calendar.timegm(utc.timetuple())


def count_web_commits(commits, prs):
    """
    STAT-15: count each author's commits that GitHub created itself, other
    than the result of merging a pull request. A merge result is the commit
    GitHub names as a pull request's merge commit, or one committed at the
    same moment (within MERGE_TIME_TOLERANCE seconds) as that commit, which
    covers the other commits of a rebase merge. GitHub commits the merge
    result a few seconds before it stamps the pull request merged, so a pull
    request without a merge commit is compared by its merge time instead.
    @param commits: dicts with "hash", "name" (author), "committer_email" and
        "committed" (committer time, seconds since the epoch), for the
        commits counted in STAT-1
    @param prs: the list from fetch_pull_requests
    @returns: {author name: number of website commits}
    """
    merge_hashes = set()
    merge_times = []
    for pr in prs:
        if not pr["merged_at"]:
            continue
        merged = _utc_seconds(pr["merged_at"])
        committed = _utc_seconds(pr.get("merge_committed_at") or pr["merged_at"])
        if abs(merged - committed) > MERGE_COMMIT_LAG:
            continue  # the pull request's own head commit, made earlier
        if pr.get("merge_commit"):
            merge_hashes.add(pr["merge_commit"])
        merge_times.append(committed)
    counts = {}
    for commit in commits:
        if commit["committer_email"].strip().casefold() != GITHUB_COMMITTER_EMAIL:
            continue
        if commit["hash"] in merge_hashes or any(
            abs(commit["committed"] - merged) <= MERGE_TIME_TOLERANCE
            for merged in merge_times
        ):
            continue
        counts[commit["name"]] = counts.get(commit["name"], 0) + 1
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
