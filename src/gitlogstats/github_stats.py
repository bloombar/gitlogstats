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
    GITHUB_FIELDNAMES,
    GitHubError,
    commit_login,
    contributor_logins,
    count_pull_requests,
    fetch_pull_requests,
    github_repo_from_url,
    user_profile,
)
from .identity import consolidate, match_identities, unavailable_row

# the columns that show activity; a row with all of these zero or empty is idle
ACTIVITY_FIELDS = FIELDNAMES[4:] + GITHUB_FIELDNAMES[1:]


def warn(repo_url, reason):
    """
    CLI-3: tell the user why a repository has no GitHub statistics.
    @param repo_url: the repository as given on the command line
    @param reason: why GitHub could not be used
    """
    print(
        f"gitlogstats: no GitHub statistics for {repo_url}: {reason}", file=sys.stderr
    )


def combine(parser, rows, identities, github_repo, args):
    """
    STAT-8 to STAT-11: fetch the repository's pull requests, match GitHub users
    to git authors and merge their rows.
    @param parser: the GitLogsParser of the repository (for verbose output)
    @param rows: git rows from parser.parse(), unfiltered
    @param identities: {author_name: {email: commit hash}} from get_identities
    @param github_repo: "owner/repo"
    @param args: the parsed command-line arguments (start, end, branch)
    @returns: (combined rows, {author_name: (login, tier)})
    @raises GitHubError: if GitHub cannot be read for this repository
    """
    api_calls = 2  # the pull request list and the contributor list
    prs = fetch_pull_requests(github_repo)
    pr_counts = count_pull_requests(prs, args.start, args.end, args.branch)

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
    parser.verboseprint(f"GitHub API calls: {api_calls}")

    repository = GitLogsParser.repo_name_from_url(parser.repository)
    combined = consolidate(rows, matches, pr_counts, repository, args.start, args.end)
    return combined, matches


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
        result = [unavailable_row(row) for row in rows]

    if args.user:
        result = [r for r in result if keep_user(r, args.user, matches, identities)]
    if args.clean:
        result = [r for r in result if any(r[f] for f in ACTIVITY_FIELDS)]
    return result
