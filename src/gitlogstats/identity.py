"""Match git authors to GitHub users and merge their rows (STAT-11).

Everything here is pure logic over plain data: no git, no network. The caller
gathers the inputs (author names and emails from git, GitHub users and linked
emails from the GitHub API) and passes them in.
"""

import re
import unicodedata

from gitlogstats.git_logs_parser import FIELDNAMES
from gitlogstats.github import (
    ACTIVITY_FIELDNAMES,
    EMAIL_FIELDNAMES,
    GITHUB_FIELDNAMES,
)

NOREPLY_RE = re.compile(
    r"^(?:\d+\+)?([^@+\s]+)@users\.noreply\.github\.com$", re.IGNORECASE
)

# the matching tiers, in the order they are tried
TIER_EMAIL = "email"
TIER_USERNAME = "username"
TIER_DISPLAY_NAME = "display_name"

# email local parts that name a role or service, not a person, so they are
# never compared with logins (e.g. GitHub's own noreply@github.com committer)
GENERIC_LOCAL_PARTS = {
    "admin",
    "contact",
    "dev",
    "developer",
    "git",
    "github",
    "info",
    "mail",
    "me",
    "noreply",
    "root",
    "student",
    "test",
    "user",
}

_SUMMED_FIELDS = ["commits", "insertions", "deletions", "files", "merges"]
_PR_FIELDS = GITHUB_FIELDNAMES[1:]
# per-GitHub-user counts: pull requests (STAT-8 to 12) and pushes (STAT-14)
_USER_FIELDS = _PR_FIELDS + ACTIVITY_FIELDNAMES[:1]


def login_from_noreply(email):
    """
    Extract the GitHub login from a GitHub noreply address.
    @param email: an email address, e.g. 12345+login@users.noreply.github.com.
    @returns: the login, or None if the address is not a noreply address.
    """
    match = NOREPLY_RE.match((email or "").strip())
    return match.group(1) if match else None


def normalize_login(text):
    """
    Reduce a name or login so that spacing, case and -, _, . do not matter.
    @param text: an author name, email local part or login.
    @returns: the casefolded text without spaces, hyphens, underscores or dots.
    """
    folded = (text or "").casefold()
    return "".join(ch for ch in folded if ch not in " -_.")


def normalize_display_name(text):
    """
    Reduce a display name to a key that ignores case, accents, punctuation and
    word order.
    @param text: a person's name, e.g. "Hopper, Grace".
    @returns: a tuple of sorted words; empty if there are no words.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    words = re.split(r"[\W_]+", stripped.casefold())
    return tuple(sorted(word for word in words if word))


def _add(found, login, spelling):
    """Record a login under its casefolded key, preferring a known spelling."""
    if login:
        key = login.casefold()
        found.setdefault(key, spelling.get(key, login))


def match_identities(identities, candidates, linked_emails):
    """
    Decide which GitHub user each git author name is (STAT-11).

    Each tier collects the distinct logins it suggests. Exactly one is a match;
    several are ambiguous and the next tier is tried; none goes to the next tier.
    @param identities: {author_name: set of emails}.
    @param candidates: {login: {"name": display name or None, "email": public
        email or None}} for GitHub users active in the repository.
    @param linked_emails: {email: login or None} as linked by GitHub's commits.
    @returns: (matches, ambiguous). matches is {author_name: (login, tier)};
        ambiguous is {author_name: [tiers that were ambiguous]}.
    """
    spelling = {login.casefold(): login for login in candidates}
    linked = {
        email.casefold(): login for email, login in linked_emails.items() if login
    }
    public_emails = {}
    for login, info in candidates.items():
        email = (info or {}).get("email")
        if email:
            public_emails.setdefault(email.casefold(), []).append(login)
    display_keys = {
        login: normalize_display_name((info or {}).get("name"))
        for login, info in candidates.items()
    }

    # an email local part shared by several author names (alex@gmail and
    # alex@school) could be either person, so it is not used to match anyone
    local_part_owners = {}
    for name, emails in identities.items():
        for email in emails:
            if email:
                local = normalize_login(email.split("@")[0])
                local_part_owners.setdefault(local, set()).add(name)

    matches = {}
    ambiguous = {}
    for name, emails in identities.items():
        emails = [email for email in emails if email]

        # STAT-11 tier 1: email
        email_found = {}
        for email in emails:
            _add(email_found, login_from_noreply(email), spelling)
            _add(email_found, linked.get(email.casefold()), spelling)
            for login in public_emails.get(email.casefold(), []):
                _add(email_found, login, spelling)

        # STAT-11 tier 2: username
        wanted = {normalize_login(name)}
        for email in emails:
            local = normalize_login(email.split("@")[0])
            if local not in GENERIC_LOCAL_PARTS and local_part_owners[local] == {name}:
                wanted.add(local)
        wanted.discard("")
        username_found = {}
        for login in candidates:
            if normalize_login(login) in wanted:
                _add(username_found, login, spelling)

        # STAT-11 tier 3: display name
        name_key = normalize_display_name(name)
        display_found = {}
        if name_key:
            for login, key in display_keys.items():
                if key == name_key:
                    _add(display_found, login, spelling)

        for tier, found in (
            (TIER_EMAIL, email_found),
            (TIER_USERNAME, username_found),
            (TIER_DISPLAY_NAME, display_found),
        ):
            if len(found) == 1:
                matches[name] = (next(iter(found.values())), tier)
                break
            if len(found) > 1:
                ambiguous.setdefault(name, []).append(tier)
    return matches, ambiguous


def join_emails(emails):
    """
    STAT-13: list email addresses for the git_email column.
    @param emails: an iterable of email addresses (empty ones are ignored).
    @returns: the distinct addresses (ignoring case; the first in plain
        sorted order is kept) sorted ignoring case and joined with "; ".
    """
    unique = {}
    for email in sorted(set(emails)):
        if email:
            unique.setdefault(email.casefold(), email)
    return "; ".join(unique[key] for key in sorted(unique))


def _blank_row(row):
    """Return a copy of a git row in output column order, GitHub columns unset."""
    out = {field: row[field] for field in FIELDNAMES}
    out["github_username"] = ""
    for field in _PR_FIELDS:
        out[field] = 0
    out["git_email"] = ""
    out["github_email"] = ""
    out["pushes_to_default"] = 0
    out["web_commits"] = row.get("web_commits", 0)  # STAT-15
    return out


def consolidate(
    rows, matches, pr_counts, repository, start, end, identities, github_emails
):
    """
    Merge git rows that belong to one GitHub user and add their GitHub counts.

    Rows matched to the same login become one row: the username is the member
    with the most commits (ties alphabetical) and the statistics are summed.
    GitHub users with pull requests or pushes but no git row get a row of their
    own, appended after the git rows in login order.
    @param rows: git rows for one repository, from GitLogsParser.parse(); a
        row may have a "web_commits" count (STAT-15), which is summed.
    @param matches: {author_name: (login, tier)} from match_identities.
    @param pr_counts: {login: {PR column or pushes_to_default: count}}, the
        counts of each GitHub user (missing columns count as 0).
    @param repository: kept for GitHub-only rows.
    @param start: start date kept for GitHub-only rows.
    @param end: end date kept for GitHub-only rows.
    @param identities: {author_name: emails} (STAT-13); for git_email.
    @param github_emails: {login: public profile email or None} (STAT-13).
    @returns: new rows with keys FIELDNAMES + GITHUB_FIELDNAMES +
        EMAIL_FIELDNAMES + ACTIVITY_FIELDNAMES.
    """
    counts = {login.casefold(): value for login, value in pr_counts.items()}
    profile_emails = {login.casefold(): e for login, e in github_emails.items()}

    # group rows by login, remembering where each group first appears
    slots = []  # entries: ("row", row) or ("group", key)
    groups = {}
    spellings = {}
    for row in rows:
        match = matches.get(row["username"])
        if match is None:
            slots.append(("row", row))
            continue
        key = match[0].casefold()
        if key not in groups:
            groups[key] = []
            spellings[key] = match[0]
            slots.append(("group", key))
        groups[key].append(row)

    def with_counts(out, login):
        out["github_username"] = login
        found = counts.get(login.casefold(), {})
        for field in _USER_FIELDS:
            out[field] = found.get(field, 0)
        out["github_email"] = profile_emails.get(login.casefold()) or ""
        return out

    result = []
    for kind, item in slots:
        if kind == "row":
            out = _blank_row(item)
            out["git_email"] = join_emails(identities.get(item["username"], ()))
            result.append(out)
            continue
        members = groups[item]
        best = min(members, key=lambda r: (-r["commits"], r["username"]))
        out = _blank_row(members[0])
        out["username"] = best["username"]
        for field in _SUMMED_FIELDS:
            out[field] = sum(member[field] for member in members)
        out["web_commits"] = sum(member.get("web_commits", 0) for member in members)
        out["git_email"] = join_emails(
            email
            for member in members
            for email in identities.get(member["username"], ())
        )
        result.append(with_counts(out, spellings[item]))

    # STAT-11 tier 4: GitHub users that no git identity matched
    for login in sorted(pr_counts, key=str.casefold):
        if login.casefold() in groups:
            continue
        out = _blank_row({field: 0 for field in FIELDNAMES})
        out.update({"username": "", "repository": repository})
        out.update({"start_date": start, "end_date": end})
        result.append(with_counts(out, login))
    return result


def unavailable_row(row, emails=()):
    """
    Copy a git row with the GitHub columns marked unavailable (CLI-3). The
    git_email column is still filled in (STAT-13).
    @param row: a git row.
    @param emails: the author emails of the row's git identity.
    @returns: a new row whose GitHub columns are None, except git_email.
    """
    out = {field: row[field] for field in FIELDNAMES}
    for field in GITHUB_FIELDNAMES + EMAIL_FIELDNAMES + ACTIVITY_FIELDNAMES:
        out[field] = None
    out["git_email"] = join_emails(emails)
    return out
