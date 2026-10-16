"""Combine result rows by developer or by repository (OUT-6).

Everything here is pure logic over the rows the rest of the tool produces: no
git, no network. Each aggregated row sums the counts of the rows it combines.
"""

from gitlogstats.git_logs_parser import FIELDNAMES
from gitlogstats.github import ACTIVITY_FIELDNAMES, EMAIL_FIELDNAMES
from gitlogstats.identity import join_emails

DEVELOPER = "developer"
REPOSITORY = "repository"
MODES = [DEVELOPER, REPOSITORY]

# the git counts, summed in both modes
GIT_COUNTS = ["commits", "insertions", "deletions", "files", "merges"]

# the GitHub pull-request counts (CLI-3), summed in both modes
PR_COUNTS = ["prs_opened", "prs_merged", "prs_closed_unmerged", "prs_self_merged"]


def fieldnames(mode, github):
    """
    The output columns of an aggregated table, in order.
    @param mode: DEVELOPER or REPOSITORY
    @param github: whether the GitHub columns are reported (--github)
    @returns: a list of column names
    """
    dates = ["start_date", "end_date"]
    if mode == DEVELOPER:
        columns = ["username"] + dates + GIT_COUNTS + ["repositories"]
        if github:
            columns += ["github_username"] + PR_COUNTS + EMAIL_FIELDNAMES
            columns += ACTIVITY_FIELDNAMES
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


def combine(rows, mode, github):
    """
    Build the aggregated row of one group.
    @param rows: the rows of one developer or one repository
    @param mode: DEVELOPER or REPOSITORY
    @param github: whether the GitHub columns are reported (--github)
    @returns: one row with the columns of fieldnames(mode, github)
    """
    first = rows[0]
    out = {}
    for field in fieldnames(mode, github):
        if field == "username":
            out[field] = first_text(row["username"] for row in rows)
        elif field in ("repository", "start_date", "end_date"):
            out[field] = first[field]
        elif field == "repositories":
            out[field] = len({row["repository"] for row in rows})
        elif field == "contributors":
            out[field] = len(rows)
        elif field == "github_username":
            out[field] = first_text(row[field] for row in rows)
        elif field in EMAIL_FIELDNAMES:
            out[field] = merge_emails(row[field] for row in rows)
        else:
            out[field] = sum_values(row[field] for row in rows)
    return out


def sort_key(row):
    """
    The order of aggregated rows: by username (or GitHub username, for a row
    with no git username) or repository, ignoring case.
    @param row: an aggregated row
    @returns: a sortable value
    """
    name = row.get("username", row.get("repository")) or row.get("github_username")
    name = name or ""
    return (name.casefold(), name)


def aggregate(rows, mode, github):
    """
    Combine result rows into one row per developer or one row per repository.
    @param rows: result rows of every repository, after -u and -c
    @param mode: DEVELOPER or REPOSITORY
    @param github: whether the rows carry the GitHub columns (--github)
    @returns: the aggregated rows, sorted
    """
    groups = {}
    for row in rows:
        key = developer_key(row) if mode == DEVELOPER else row["repository"]
        groups.setdefault(key, []).append(row)
    combined = [combine(group, mode, github) for group in groups.values()]
    return sorted(combined, key=sort_key)
