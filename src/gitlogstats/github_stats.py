"""
Put GitHub pull-request statistics on a repository's git rows (CLI-3).

This is the glue between the git parser, the GitHub CLI wrappers (github.py)
and the matching logic (identity.py). Messages for the user go to standard
error; the rows are returned for the caller to print.
"""

import sys

from .git_logs_parser import FIELDNAMES, GitLogsParser
from .github import (
    GHOST_LOGIN,
    ACTIVITY_FIELDNAMES,
    GITHUB_FIELDNAMES,
    GitHubError,
    commit_login,
    contributor_logins,
    count_pull_requests,
    count_pushes,
    count_web_commits,
    GITHUB_COMMITTER_EMAIL,
    events_by_day,
    fetch_pull_requests,
    fetch_pushes,
    github_repo_from_url,
    local_day,
    user_profile,
)
from .identity import consolidate, match_identities, unavailable_row

# the columns that show activity; a row with all of these zero or empty is idle
ACTIVITY_FIELDS = FIELDNAMES[4:] + GITHUB_FIELDNAMES[1:] + ACTIVITY_FIELDNAMES


def warn(repo_url, reason):
    """
    CLI-3: tell the user why a repository has no GitHub statistics.
    @param repo_url: the repository as given on the command line
    @param reason: why GitHub could not be used
    """
    print(
        f"gitlogstats: no GitHub statistics for {repo_url}: {reason}", file=sys.stderr
    )


def fetch(parser, identities, github_repo):
    """
    STAT-8 to STAT-11, STAT-14, STAT-15: fetch the repository's pull requests,
    pushes and website-commit candidates, and match GitHub users to git authors.
    Nothing is counted yet, so the result serves any date range (OUT-7).
    @param parser: the GitLogsParser of the repository (for verbose output)
    @param identities: {author_name: {email: commit hash}} from get_identities
    @param github_repo: "owner/repo"
    @returns: a dict with prs, pushes (to the checked-out branch), commits (committed_commits), matches
        ({author_name: (login, tier)}) and github_emails ({login: email})
    @raises GitHubError: if GitHub cannot be read for this repository
    """
    api_calls = 3  # the pull request, contributor and activity lists
    prs = fetch_pull_requests(github_repo)

    # STAT-14: pushes to the branch that was actually analyzed; a detached
    # HEAD is no branch, so nothing was pushed to it
    branch = parser.current_branch()
    if branch is None:
        api_calls -= 1
        pushes = []
    else:
        pushes = fetch_pushes(github_repo, branch)

    logins = {pr["login"] for pr in prs} | contributor_logins(github_repo)
    candidates = {}
    for login in sorted(logins):
        profile = {"name": None, "email": None}
        if login != GHOST_LOGIN:
            api_calls += 1
            try:
                profile = user_profile(login)
            except GitHubError as exc:
                # only a missing profile is skipped; a rate limit or network
                # error must not quietly drop matching tiers (CLI-3)
                if "(HTTP 404)" not in str(exc):
                    raise
        candidates[login] = profile

    # one commit per email shows which account GitHub links that email to
    linked_emails = {}
    for emails in identities.values():
        for email, sha in emails.items():
            if email not in linked_emails:
                api_calls += 1
                linked_emails[email] = commit_login(github_repo, sha)

    matches, ambiguous = match_identities(
        {name: set(emails) for name, emails in identities.items()},
        candidates,
        linked_emails,
    )
    for name, (login, tier) in sorted(matches.items()):
        parser.verboseprint(f"GitHub match: {name} -> {login} ({tier})")
    for name, tiers in sorted(ambiguous.items()):
        parser.verboseprint(f"GitHub ambiguous: {name} ({', '.join(tiers)})")
    for name in sorted(set(identities) - set(matches)):
        parser.verboseprint(f"GitHub unmatched: {name}")

    # STAT-13: public emails of the matched users; a matched user who was not
    # a candidate (found through a linked email) has a profile fetched now
    github_emails = {
        login: (info or {}).get("email") for login, info in candidates.items()
    }
    known = {login.casefold() for login in candidates}
    for login, _tier in matches.values():
        if login.casefold() in known:
            continue
        known.add(login.casefold())
        api_calls += 1
        try:
            github_emails[login] = user_profile(login)["email"]
        except GitHubError as exc:
            if "(HTTP 404)" not in str(exc):
                raise
    parser.verboseprint(f"GitHub API calls: {api_calls}")
    return {
        "prs": prs,
        "pushes": pushes,
        "commits": parser.committed_commits(),
        "matches": matches,
        "github_emails": github_emails,
    }


def tally(parser, rows, data, identities, start, end, branch, events=None):
    """
    Count the fetched GitHub activity in a date range and merge it into the
    git rows of the same range.
    @param parser: the GitLogsParser of the repository
    @param rows: git rows for the range, unfiltered
    @param data: the result of fetch
    @param identities: {author_name: {email: commit hash}} from get_identities
    @param start: first day, mm/dd/yyyy
    @param end: last day, mm/dd/yyyy
    @param branch: count only pull requests with this base branch, if given
    @param events: {"prs", "pushes", "commits"} limited to the range (OUT-7);
        defaults to everything in data (the whole -s/-e range)
    @returns: the combined rows
    """
    events = events or data
    pr_counts = count_pull_requests(events["prs"], start, end, branch)
    pushes = count_pushes(events["pushes"], start, end)
    known = {login.casefold(): login for login in pr_counts}
    for login, number in pushes.items():
        key = known.setdefault(login.casefold(), login)
        found = pr_counts.setdefault(key, {})
        found["pushes_to_default"] = found.get("pushes_to_default", 0) + number

    # STAT-15: commits GitHub created itself, apart from pull request merges
    web_commits = count_web_commits(events["commits"], data["prs"])
    rows = [dict(row, web_commits=web_commits.get(row["username"], 0)) for row in rows]

    repository = GitLogsParser.repo_name_from_url(parser.repository)
    return consolidate(
        rows,
        data["matches"],
        pr_counts,
        repository,
        start,
        end,
        identities,
        data["github_emails"],
    )


def combine(parser, rows, identities, github_repo, args):
    """
    STAT-8 to STAT-11, STAT-14, STAT-15: fetch the repository's pull requests
    and pushes, match GitHub users to git authors and merge their rows.
    @param parser: the GitLogsParser of the repository (for verbose output)
    @param rows: git rows from parser.parse(), unfiltered
    @param identities: {author_name: {email: commit hash}} from get_identities
    @param github_repo: "owner/repo"
    @param args: the parsed command-line arguments (start, end, branch)
    @returns: (combined rows, {author_name: (login, tier)})
    @raises GitHubError: if GitHub cannot be read for this repository
    """
    data = fetch(parser, identities, github_repo)
    combined = tally(parser, rows, data, identities, args.start, args.end, args.branch)
    return combined, data["matches"]


def member_names(row, matches):
    """
    List the git author names that make up a combined row.
    @param row: a row from combine or unavailable_row
    @param matches: {author_name: (login, tier)}
    @returns: a list of author names (empty for a GitHub-only row)
    """
    login = row["github_username"]
    if login:
        key = login.casefold()
        return [name for name, found in matches.items() if found[0].casefold() == key]
    return [row["username"]] if row["username"] else []


def keep_user(row, user, matches, identities):
    """
    CLI-3: whether -u selects a row: the value equals one of its author names
    or emails exactly, or its GitHub username ignoring case.
    """
    names = member_names(row, matches)
    if user in names:
        return True
    if any(user in identities.get(name, {}) for name in names):
        return True
    return bool(row["github_username"]) and user.casefold() == (
        row["github_username"].casefold()
    )


def github_rows(parser, rows, repo_url, identities, args):
    """
    Add the GitHub columns to one repository's rows and apply -u and -c.
    If GitHub cannot be used for this repository, say why on standard error and
    keep its git statistics with the GitHub columns unavailable (None).
    @param parser: the GitLogsParser of the repository
    @param rows: git rows from parser.parse() with no -u or -c applied
    @param repo_url: the repository as given on the command line
    @param identities: {author_name: {email: commit hash}} from get_identities
    @param args: the parsed command-line arguments
    @returns: the final rows for this repository
    """
    matches = {}
    github_repo = github_repo_from_url(repo_url)
    try:
        if github_repo is None:
            raise GitHubError("not a github.com repository")
        result, matches = combine(parser, rows, identities, github_repo, args)
    except GitHubError as exc:
        warn(repo_url, exc)
        result = unavailable_rows(rows, identities)

    return select(result, args, matches, identities)


def unavailable_rows(rows, identities):
    """
    Mark the GitHub columns of git rows unavailable (CLI-3), keeping any
    "date" (OUT-7).
    @param rows: git rows
    @param identities: {author_name: {email: commit hash}} from get_identities
    @returns: new rows from unavailable_row
    """
    result = []
    for row in rows:
        out = unavailable_row(row, identities.get(row["username"], ()))
        if "date" in row:
            out["date"] = row["date"]
        result.append(out)
    return result


def github_day_rows(parser, repo_url, identities, args):
    """
    OUT-7: like github_rows, one day at a time. GitHub is read once; each
    event is counted on its own local day.
    @param parser: the GitLogsParser of the repository
    @param repo_url: the repository as given on the command line
    @param identities: {author_name: {email: commit hash}} from get_identities
    @param args: the parsed command-line arguments
    @returns: the final rows for this repository, each with a "date" key
    """
    matches = {}
    github_repo = github_repo_from_url(repo_url)
    result = []
    try:
        if github_repo is None:
            raise GitHubError("not a github.com repository")
        data = fetch(parser, identities, github_repo)
    except GitHubError as exc:
        warn(repo_url, exc)
        result = unavailable_rows(parser.day_rows(), identities)
    else:
        matches = data["matches"]
        days = events_by_day(
            data["prs"], data["pushes"], args.start, args.end, args.branch
        )
        # STAT-15: only commits GitHub committed can be website commits
        none = {"prs": [], "pushes": [], "commits": []}
        for commit in data["commits"]:
            if commit["committer_email"].strip().casefold() == GITHUB_COMMITTER_EMAIL:
                day = local_day(commit["committed"])
                days.setdefault(day, dict(none, commits=[]))["commits"].append(commit)
        for day, rows in parser.parse_days(days).items():
            events = days.get(day, none)
            for row in tally(
                parser, rows, data, identities, day, day, args.branch, events
            ):
                result.append(dict(row, date=day))
    return select(result, args, matches, identities)


def select(rows, args, matches, identities):
    """
    Apply -u and -c to combined rows (CLI-3).
    @param rows: rows from tally or unavailable_row
    @param args: the parsed command-line arguments (user, clean)
    @param matches: {author_name: (login, tier)}
    @param identities: {author_name: {email: commit hash}} from get_identities
    @returns: the rows that -u and -c keep
    """
    if args.user:
        rows = [r for r in rows if keep_user(r, args.user, matches, identities)]
    if args.clean:
        rows = [r for r in rows if any(r[f] for f in ACTIVITY_FIELDS)]
    return rows
