"""Combine result rows by developer or by repository (OUT-6), or by day (OUT-7).

Everything here is pure logic over the rows the rest of the tool produces: no
git, no network. Each aggregated row sums the counts of the rows it combines.
"""

import datetime

from gitlogstats.git_logs_parser import FIELDNAMES
from gitlogstats.github import (
    ACTIVITY_FIELDNAMES,
    EMAIL_FIELDNAMES,
    GITHUB_FIELDNAMES,
)
from gitlogstats.identity import join_emails

DEVELOPER = "developer"
REPOSITORY = "repository"
DAY = "day"
MODES = [DEVELOPER, REPOSITORY, DAY]

# the git counts (commits to merges), summed in every mode
GIT_COUNTS = FIELDNAMES[4:]

# the GitHub pull-request counts (CLI-3), summed in every mode
PR_COUNTS = GITHUB_FIELDNAMES[1:]

# every count; a row with any of them non-zero is active, as for -c (FILT-4)
ALL_COUNTS = GIT_COUNTS + PR_COUNTS + ACTIVITY_FIELDNAMES


def fieldnames(mode, github):
    """
    The output columns of an aggregated table, in order.
    @param mode: DEVELOPER, REPOSITORY or DAY
    @param github: whether the GitHub columns are reported (--github)
    @returns: a list of column names
    """
    dates = ["start_date", "end_date"]
    if mode == DEVELOPER:
        columns = ["username"] + dates + GIT_COUNTS + ["repositories"]
        if github:
            columns += ["github_username"] + PR_COUNTS + EMAIL_FIELDNAMES
            columns += ACTIVITY_FIELDNAMES
    elif mode == DAY:
        columns = ["date"] + GIT_COUNTS + ["repositories", "contributors"]
        if github:
            columns += PR_COUNTS + ACTIVITY_FIELDNAMES
    else:
        columns = ["repository"] + dates + GIT_COUNTS + ["contributors"]
        if github:
            columns += PR_COUNTS + ACTIVITY_FIELDNAMES
    return columns


def developer_key(row):
    """
    The developer a row belongs to: its GitHub user, ignoring case, when it
    has one, otherwise its exact git username.
    @param row: a result row
    @returns: a hashable key
    """
    login = row.get("github_username")
    if login:
        return ("github", login.casefold())
    return ("git", row["username"])


def is_active(row):
    """
    Whether a row has any activity: a non-zero count, git or GitHub.
    @param row: a result row
    @returns: a bool
    """
    return any(row.get(field) for field in ALL_COUNTS)


def main_username(rows):
    """
    The git username of a developer's rows: the one with the most commits,
    ties alphabetical, as when combining identities in one repository (STAT-11).
    @param rows: the rows of one developer
    @returns: a username, or "" if every row is GitHub-only
    """
    named = [row for row in rows if row["username"]]
    if not named:
        return ""
    return min(named, key=lambda row: (-(row["commits"] or 0), row["username"]))[
        "username"
    ]


def sum_values(values):
    """
    Add up counts. An unavailable count (None, CLI-3) is skipped, so the total
    is None only when every count is unavailable.
    @param values: numbers or None
    @returns: their sum, or None
    """
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def first_text(values):
    """
    The first non-empty text. When there is none, "" if any value is
    available, or None if every value is unavailable.
    @param values: strings or None
    @returns: a string, or None
    """
    values = list(values)
    for value in values:
        if value:
            return value
    return None if all(value is None for value in values) else ""


def merge_emails(values):
    """
    Join '; '-separated email lists into one sorted list without repeats
    (STAT-13), or None if every list is unavailable.
    @param values: '; '-separated strings, "" or None
    @returns: a '; '-separated string, or None
    """
    values = list(values)
    if all(value is None for value in values):
        return None
    return join_emails(
        email for value in values if value for email in value.split("; ")
    )


def combine(rows, columns):
    """
    Build the aggregated row of one group.
    @param rows: the rows of one developer, repository or day
    @param columns: the output columns, from fieldnames()
    @returns: one row with those columns
    """
    active = [row for row in rows if is_active(row)]
    out = {}
    for field in columns:
        if field == "username":
            out[field] = main_username(rows)
        elif field in ("repository", "start_date", "end_date", "date"):
            out[field] = rows[0][field]
        elif field == "repositories":
            out[field] = len({row["repository"] for row in active})
        elif field == "contributors":
            out[field] = len({developer_key(row) for row in active})
        elif field == "github_username":
            out[field] = first_text(row[field] for row in rows)
        elif field in EMAIL_FIELDNAMES:
            out[field] = merge_emails(row[field] for row in rows)
        else:
            out[field] = sum_values(row[field] for row in rows)
    return out


def aggregate(rows, mode, github):
    """
    Combine result rows into one row per developer, repository or day. Rows
    are sorted by username (or GitHub username, for a developer with no git
    username) or by repository, ignoring case, or by date. Days only count
    active rows, so a day without activity is left out (OUT-7).
    @param rows: result rows of every repository, after -u and -c; in DAY
        mode, rows for single days, each with a "date" key
    @param mode: DEVELOPER, REPOSITORY or DAY
    @param github: whether the rows carry the GitHub columns (--github)
    @returns: the aggregated rows, sorted
    """
    groups = {}
    for row in rows:
        if mode == DEVELOPER:
            key = developer_key(row)
        elif mode == REPOSITORY:
            key = row["repository"]
        elif is_active(row):
            key = row["date"]
        else:
            continue
        groups.setdefault(key, []).append(row)
    columns = fieldnames(mode, github)
    combined = [combine(group, columns) for group in groups.values()]

    def sort_key(row):
        if mode == DAY:
            return (datetime.datetime.strptime(row["date"], "%m/%d/%Y"), "")
        if mode == DEVELOPER:
            name = row["username"] or row.get("github_username") or ""
        else:
            name = row["repository"]
        return (name.casefold(), name)

    return sorted(combined, key=sort_key)
