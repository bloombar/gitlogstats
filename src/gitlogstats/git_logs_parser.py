#!/usr/bin/env python3

import os
import sys
import subprocess
import datetime
import csv
import io
import re
import json

# Each commit's header in the git log output starts with this record separator,
# followed by the hash, author name, and author email, separated by unit
# separators. Control characters cannot appear in names or emails, and commit
# messages are never printed, so message contents can never confuse the parser.
RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
LOG_FORMAT = f"--format={RECORD_SEP}%H{FIELD_SEP}%aN{FIELD_SEP}%aE"

# OUT-7: the same header with the commit date, as a local mm/dd/yyyy day
DAY_LOG_FORMAT = f"{LOG_FORMAT}{FIELD_SEP}%cd"
DAY_DATE_ARG = "--date=format-local:%m/%d/%Y"

FILES_RE = re.compile(r"(\d+) files? changed")
INSERTIONS_RE = re.compile(r"(\d+) insertions?\(\+\)")
DELETIONS_RE = re.compile(r"(\d+) deletions?\(-\)")

# STAT-15: the header of each commit when listing who committed it and when
COMMITTER_LOG_FORMAT = (
    f"--format={RECORD_SEP}%H{FIELD_SEP}%aN{FIELD_SEP}%aE{FIELD_SEP}%cE{FIELD_SEP}%ct"
)

# the fields reported for each contributor, in output order
FIELDNAMES = [
    "username",
    "repository",
    "start_date",
    "end_date",
    "commits",
    "insertions",
    "deletions",
    "files",
    "merges",
]


class GitLogsParser:
    def __init__(
        self,
        repo,
        start,
        end,
        username,
        exclusions=None,
        repofile=None,
        verbose=False,
        clean=False,
    ):
        """
        Initialize the git logs parser for a given repository
        @param repo: the path to the repository of interest.
        @param start: the start date of interest, in standard US format, e.g. 01/01/2021. defaults to exactly 1 year ago.
        @param end: the end date of interest, in standard US format, e.g. 12/31/2021.  defaults to today's date.
        @param username: an optional username of interest.  if not present, we report all contributing users
        @param exclusions: a list of files to exclude from analysis.  wild cards accepted, e.g. ['foo.csv', '*.zip', '*.jpg']
        @param verbose: whether to output debugging info.  defaults to False.
        @param clean: remove contributors without any contribuition.  defaults to False.
        """

        self.repository = repo
        self.repofile = repofile
        self.start = start
        self.end = end
        self.username = username
        self.exclusions = exclusions if exclusions is not None else []
        self.verbose = verbose
        self.clean = clean

        # go into the selected repository directory, if any
        if self.repository:
            self.verboseprint(f"Switching to: {self.repository}...")
            os.chdir(self.repository)

    def get_contributors(self):
        """
        Return a list of contributors to this repository.
        @returns: a sorted list of all contributors' git usernames
        """
        contributors = set()  # a set that will include all contributors

        # use git logs to get all contributor usernames
        cmd = ["git", "log", "--format=%aN"]
        with subprocess.Popen(
            cmd, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True
        ) as p:
            for line in p.stdout:
                line = line.strip().strip("'")  # remove line break and any quotes
                if line:
                    contributors.add(line)  # add to set

        contributors = sorted(contributors)  # sorted for stable output
        self.verboseprint(f"Contributors: {', '.join(contributors)}...")
        return contributors

    def get_identities(self):
        """
        Return every identity (author name and email) in this repository's
        history, the same population as get_contributors (STAT-11).
        @returns: {author_name: {email: hash of one commit with that identity}}
        """
        cmd = ["git", "log", LOG_FORMAT]
        self.verboseprint(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, check=True)
        identities = {}
        for record in result.stdout.decode("utf-8", errors="replace").split(RECORD_SEP)[
            1:
        ]:
            fields = record.strip("\n").split(FIELD_SEP)
            name = fields[1].strip().strip("'")  # as get_contributors does
            if name:
                identities.setdefault(name, {}).setdefault(fields[2], fields[0])
        return identities

    def date_range_args(self):
        """
        Build the git log options that limit commits to the date range.
        The range is inclusive: from the very start of the start date to the
        very end of the end date.
        @returns: a list of git log arguments
        """
        since = datetime.datetime.strptime(self.start, "%m/%d/%Y")
        until = datetime.datetime.strptime(self.end, "%m/%d/%Y").replace(
            hour=23, minute=59, second=59
        )
        return [
            f"--since={since:%Y-%m-%d %H:%M:%S}",
            f"--until={until:%Y-%m-%d %H:%M:%S}",
        ]

    def git_log_command(self, log_format=LOG_FORMAT, shortstat=True, by_day=False):
        """
        Build the git log command that lists every non-merge commit in the date
        range with its author and a one-line summary of its changes. Merge
        commits come from merge_log_command instead.
        @param log_format: the --format argument
        @param shortstat: whether to add the summary of changes
        @param by_day: whether to add each commit's day (OUT-7); replaces log_format
        @returns: the command as a list of arguments, ready for subprocess
        """
        if by_day:
            log_format = DAY_LOG_FORMAT
        # --full-history stops git from hiding commits while simplifying the
        # history for the path filter below; merges are counted separately
        cmd = [
            "git",
            "log",
            "--full-history",
            "--no-merges",
            *(["--shortstat"] if shortstat else []),
            log_format,
            *([DAY_DATE_ARG] if by_day else []),
            *self.date_range_args(),
            "--",
            ".",
        ]
        cmd += self.exclusion_pathspecs()
        return cmd

    def exclusion_pathspecs(self):
        """
        Convert the exclusions to git pathspecs. Each one is matched in any
        directory, and if it names a directory (e.g. 'vendor' or 'vendor/'),
        everything inside that directory is excluded too.
        @returns: a list of git pathspec arguments
        """
        pathspecs = []
        for exclusion in self.exclusions:
            pattern = exclusion.strip().rstrip("/")
            if pattern:
                pathspecs.append(f":(exclude,glob)**/{pattern}")
                pathspecs.append(f":(exclude,glob)**/{pattern}/**")
        return pathspecs

    def merge_log_command(self, by_day=False):
        """
        Build the git log command that lists the merge commits made directly on
        the analyzed branch in the date range, with their authors.
        Merges made inside other branches (e.g. merging main into a feature
        branch to update it) are not on the branch's first-parent line, so they
        are left out. File exclusions do not apply: a merge brings in a branch,
        whichever files it touches.
        @param by_day: whether to add each merge's day (OUT-7)
        @returns: the command as a list of arguments, ready for subprocess
        """
        return [
            "git",
            "log",
            "--first-parent",
            "--merges",
            *([DAY_LOG_FORMAT, DAY_DATE_ARG] if by_day else [LOG_FORMAT]),
            *self.date_range_args(),
        ]

    def current_branch(self):
        """
        Name the branch checked out in the repository.
        @returns: the branch name, or None if HEAD is detached
        """
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True
        )
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace").strip()

    def committed_commits(self):
        """
        STAT-15: list the commits counted in `commits` (STAT-1: the same date
        range, exclusions and branch, merges left out) with their committers.
        @returns: a list of dicts with hash, name (author), email (author),
            committer_email and committed (committer time, epoch seconds)
        """
        cmd = self.git_log_command(COMMITTER_LOG_FORMAT, shortstat=False)
        self.verboseprint(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, check=True)
        commits = []
        for record in result.stdout.decode("utf-8", errors="replace").split(RECORD_SEP)[
            1:
        ]:
            fields = record.strip("\n").split(FIELD_SEP)
            commits.append(
                {
                    "hash": fields[0],
                    "name": fields[1],
                    "email": fields[2],
                    "committer_email": fields[3],
                    "committed": int(fields[4]),
                }
            )
        return commits

    def run_git_log(self, cmd):
        """
        Run a git log command and parse its output into per-commit records.
        @param cmd: the command, from git_log_command or merge_log_command
        @returns: a list of commit dictionaries, as returned by parse_log
        """
        self.verboseprint(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, check=True)
        return self.parse_log(result.stdout.decode("utf-8", errors="replace"))

    @staticmethod
    def parse_log(logs):
        """
        Split raw git log output (produced by git_log_command) into per-commit records.
        @param logs: the text output of git log
        @returns: a list of dictionaries, one per commit, with the author's name and email and the commit's files, insertions and deletions, and its day (OUT-7) when the log has one
        """
        commits = []
        for record in logs.split(RECORD_SEP)[1:]:
            header, _, body = record.partition("\n")
            fields = header.split(FIELD_SEP)
            if len(fields) < 3:
                continue  # not a commit header
            files = FILES_RE.search(body)
            insertions = INSERTIONS_RE.search(body)
            deletions = DELETIONS_RE.search(body)
            commit = {
                "hash": fields[0],
                "name": fields[1],
                "email": fields[2],
                "files": int(files.group(1)) if files else 0,
                "insertions": int(insertions.group(1)) if insertions else 0,
                "deletions": int(deletions.group(1)) if deletions else 0,
            }
            if len(fields) > 3:
                commit["day"] = fields[3].strip()
            commits.append(commit)
        return commits

    def parse(self):
        """
        Parse the git logs and extract a breakdown of the contributions of each contributing user.
        @returns: contribution stats of all users, as a list of dictionaries, one per user
        """
        commits = self.run_git_log(self.git_log_command())
        merges = self.run_git_log(self.merge_log_command())
        return self.tally(commits, merges)

    def parse_days(self, extra_days=()):
        """
        OUT-7: parse the git logs one day at a time.
        @param extra_days: days (mm/dd/yyyy) to report even without git
            activity, e.g. days with GitHub activity
        @returns: {day: contribution stats of all users on that day, as parse()
            returns them}, for every day with a commit or merge and every extra day
        """
        commits = self.run_git_log(self.git_log_command(by_day=True))
        merges = self.run_git_log(self.merge_log_command(by_day=True))
        days = {c["day"] for c in commits + merges} | set(extra_days)
        contributors = self.contributors()  # once, not once per day
        return {
            day: self.tally(
                [c for c in commits if c["day"] == day],
                [m for m in merges if m["day"] == day],
                contributors,
            )
            for day in sorted(days)
        }

    def contributors(self):
        """
        The contributors to report: the one given with -u, or everyone.
        @returns: a list of usernames
        """
        if self.username:
            return [self.username]
        return self.get_contributors()

    def tally(self, commits, merges, contributors=None):
        """
        Credit commits and merges to each contributing user.
        @param commits: non-merge commits, from parse_log
        @param merges: merge commits, from parse_log
        @param contributors: the usernames to report; defaults to contributors()
        @returns: contribution stats of all users, as a list of dictionaries, one per user
        """
        # limit to the specified username, if any; otherwise all contributors
        if contributors is None:
            contributors = self.contributors()

        # set up stats for each contributor in dictionary form
        entries = {}
        for contributor in contributors:
            entries[contributor] = {
                "username": contributor,  # redundant, but useful
                "repository": self.repo_name_from_url(self.repository),
                "start_date": self.start,
                "end_date": self.end,
                "commits": 0,
                "insertions": 0,
                "deletions": 0,
                "files": 0,
                "merges": 0,
            }

        def entry_for(commit):
            """
            Find the stats entry to credit a commit to: its author's. A username
            given on the command line matches an author's exact name or email.
            """
            if self.username:
                if self.username in (commit["name"], commit["email"]):
                    return entries[self.username]
                return None
            # every author is a contributor, so this only misses if the history
            # changed between the two git commands
            return entries.get(commit["name"])

        for commit in commits:
            entry = entry_for(commit)
            if entry is not None:
                entry["commits"] += 1
                entry["files"] += commit["files"]
                entry["insertions"] += commit["insertions"]
                entry["deletions"] += commit["deletions"]

        # merges are counted only as merges, not commits; they add no lines or
        # files, since the merged work is credited to its own commits
        for merge in merges:
            entry = entry_for(merge)
            if entry is not None:
                entry["merges"] += 1

        stats = []
        for entry in entries.values():
            # skip contributors without any contribution, if requested
            if self.clean and (
                entry["commits"] == 0
                and entry["insertions"] == 0
                and entry["deletions"] == 0
                and entry["files"] == 0
                and entry["merges"] == 0
            ):
                continue
            stats.append(entry)
        return stats

    def format_results(self, results, output_format, fieldnames=None):
        """
        Format the parsed data in the selected format.
        @param results: A list of dictionaries, with each representing a contributor to the repository.
        @param output_format: The desired output format, e.g. 'csv', 'json', or 'markdown'
        @param fieldnames: the columns of an empty CSV table; defaults to FIELDNAMES
        """
        self.verboseprint(f"Outputting results in {output_format.upper()} format:...")
        output = ""
        # output in the selected format
        if output_format == "csv":
            # always include the header, so even an empty result is a valid
            # CSV table; quote values that contain commas, quotes, or line breaks
            buffer = io.StringIO()
            if results:
                fieldnames = list(results[0].keys())
            elif fieldnames is None:
                fieldnames = FIELDNAMES
            writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(results)
            output = buffer.getvalue()

        elif output_format == "json":
            output = json.dumps(results)

        elif output_format == "markdown":
            if len(results) > 0:
                fieldnames = results[
                    0
                ].keys()  # get the field names from the first dictionary in the list
                output += "| " + " | ".join(list(fieldnames)) + " |\n"  # headings
                output += (
                    "| " + " | ".join([":----" for key in results[0].keys()]) + " |\n"
                )  # heading separator lines
            for entry in results:
                # each row of values, with any pipes escaped so they do not split cells
                # (an unavailable value, None, is left blank)
                str_values = [
                    ("" if val is None else str(val)).replace("|", "\\|")
                    for val in entry.values()
                ]
                output += "| " + " | ".join(str_values) + " |\n"

        return output

    def get_repository_urls(self):
        """
        Returns a list repository URLs to be analyzed.
        """
        repository_urls = [self.repository]
        if self.repofile:
            with open(self.repofile, "r", encoding="utf8") as f:
                repository_urls = self.read_repository_urls(f.read())
        return repository_urls

    @staticmethod
    def read_repository_urls(text):
        """
        Extract repository URLs from the contents of a repository list file.
        Blank lines and lines starting with # are ignored.
        @param text: the contents of the file
        @returns: a list of repository URLs
        """
        urls = [line.strip() for line in text.splitlines()]
        return [url for url in urls if url and not url.startswith("#")]

    def verboseprint(self, *args):
        """
        Print out debugging info only if verbose mode has been turned on.
        Debugging info goes to stderr so it never mixes with the results on stdout.
        """
        if self.verbose:
            print(*args, file=sys.stderr)

    @staticmethod
    def repo_name_from_url(repo_url):
        """
        Extracts the humanish repository name from the full repository URL, the same way git clone names the directory.  For example, 'foo-bar' from 'https://github.com/education-automation/foo-bar.git'
        @param repo_url: The URL of the repository of interest
        @returns: The repository name, with the rest of the URL removed.
        """
        repo_name = re.split(r"[/:]", repo_url.strip().rstrip("/"))[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[: -len(".git")]
        return repo_name
