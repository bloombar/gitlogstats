import os
import subprocess
import argparse
import datetime
import re
import sys
from . import GitLogsParser
from . import aggregate
from .clones import remove_clones
from .git_logs_parser import FIELDNAMES
from .github import (
    ACTIVITY_FIELDNAMES,
    EMAIL_FIELDNAMES,
    GITHUB_FIELDNAMES,
    GitHubUnavailable,
    check_gh,
)
from .github_stats import github_rows


def valid_date(value):
    """
    Check that a command-line date is in mm/dd/yyyy format.
    @param value: the date as typed by the user
    @returns: the same date string, if valid
    """
    try:
        datetime.datetime.strptime(value, "%m/%d/%Y")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date '{value}': use mm/dd/yyyy format"
        )
    return value


def default_branch():
    """
    Find the default branch of the repository in the current directory, as recorded by git clone.
    @returns: the branch name, e.g. 'main', or None if it cannot be determined
    """
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip().split("/", 1)[-1]  # 'origin/main' -> 'main'


def main():
    """
    Generate results using the GitLogsParser with command-line arguments.
    """
    # use default dates
    today = datetime.date.today()
    str_today = today.strftime("%m/%d/%Y")  # the date today in standard US format
    last_year = datetime.datetime.now() - datetime.timedelta(
        days=365
    )  # the the date one year ago from today
    str_last_year = last_year.strftime("%m/%d/%Y")

    # default files to exclude from analysis
    exclusions = [
        "package.json",
        "package-lock.json",
        "Pipfile",
        "Pipfile.lock",
        "requirements.txt",
        "*.jpg",
        "*.png",
        "*.gif",
        "*.svg",
        "*.pdf",
        "*.zip",
        "*.gz",
        "*.tar",
        "*.csv",
        "*.json",
    ]

    # get the command-line arguments
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-r",
        "--repository",
        help="the public URL of the repository whose logs to parse",
    )
    group.add_argument(
        "-rf",
        "--repofile",
        help="the path to simple text file with a list of repository URLs to parse",
    )
    parser.add_argument(
        "-u",
        "--user",
        help="The git username (or email address) to report.  Default is all contributing users",
        default=None,
    )
    parser.add_argument(
        "-s",
        "--start",
        help="Start date in mm/dd/yyyy format",
        default=str_last_year,
        type=valid_date,
    )  # default to one year ago
    parser.add_argument(
        "-e",
        "--end",
        help="End date in mm/dd/yyyy format",
        default=str_today,
        type=valid_date,
    )  # default to today
    parser.add_argument(
        "-x",
        "--exclusions",
        help="A comma-separated list of files, patterns or directories to exclude, "
        'e.g. --exclusions "foo.zip, *.jpg, vendor". Replaces the default list; '
        'use "" to exclude nothing',
        default=",".join(exclusions),
    )
    parser.add_argument(
        "-f",
        "--format",
        help="The format in which to output the results",
        default="csv",
        choices=["csv", "json", "markdown"],
    )
    parser.add_argument(
        "-b",
        "--branch",
        help="The branch to parse, if not the default branch",
        default=None,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Whether to output debugging info",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-c",
        "--clean",
        help="Remove contributors without any contribuition",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-a",
        "--aggregate",
        help="Combine the results into one row per developer, summed over all "
        "repositories, or one row per repository, summed over its contributors",
        default=None,
        choices=aggregate.MODES,
    )
    parser.add_argument(
        "--github",
        help="Also report GitHub pull requests opened, merged, closed and "
        "self-merged per contributor, with their git and GitHub emails, their "
        "pushes to the analyzed branch and their commits made on the GitHub "
        "website, and match GitHub users to git authors. "
        "Needs the GitHub CLI (gh), signed in",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--clobber",
        help="Delete the repository clones this run used from the repos/ "
        "directory after printing the results (default: keep them for faster "
        "later runs)",
        default=False,
        action="store_true",
    )
    args = parser.parse_args()

    if datetime.datetime.strptime(args.start, "%m/%d/%Y") > datetime.datetime.strptime(
        args.end, "%m/%d/%Y"
    ):
        parser.error("the start date must not be after the end date")

    # split up comma-separated string into list, ignoring empty items
    args.exclusions = [x.strip() for x in re.split(r",", args.exclusions) if x.strip()]

    # CLI-3: check the GitHub CLI before anything is created or cloned
    if args.github:
        try:
            check_gh()
        except GitHubUnavailable as exc:
            print(exc, file=sys.stderr)
            sys.exit(1)

    # deal with repofile, if specified
    repository_urls = [args.repository]
    if args.repofile:
        with open(args.repofile, "r", encoding="utf8") as f:
            repository_urls = GitLogsParser.read_repository_urls(f.read())

    start_dir = os.getcwd()  # REPO-5: where the command was started from
    # navigate into the directory where repos will be stored
    repos_dir = os.path.join(
        os.getcwd(), "repos"
    )  # where we will clone the repos we will parse
    # make the directory where we will store the repos, if not present
    if not os.path.exists(repos_dir):
        os.makedirs(repos_dir)

    # loop through each git repository url, accumulating all results
    all_results = []
    last_parser = None
    used_clones = []  # REPO-5: the clone directories this run cloned or pulled
    for repo_url in repository_urls:
        os.chdir(repos_dir)  # start from the parent directory of all repos

        repo_dir = GitLogsParser.repo_name_from_url(
            repo_url
        )  # extract the humanish repo name from the URL
        repo_dir = os.path.join(repos_dir, repo_dir)  # convert to absolute path
        # clone the repo into the repo_dir, or update a previous clone
        if not os.path.exists(repo_dir):
            # has not yet been cloned... do a clone
            subprocess.run(
                ["git", "clone", repo_url, repo_dir], capture_output=True, check=True
            )  # clone the code from github
            os.chdir(repo_dir)  # navigate into this repository's directory
            if args.branch:
                subprocess.run(
                    ["git", "checkout", args.branch], capture_output=True, check=True
                )
        else:
            # has previously been cloned... switch to the requested branch (or
            # back to the default branch, in case an earlier run used -b), then pull
            os.chdir(repo_dir)  # navigate into this repository's directory
            branch = args.branch or default_branch()
            if branch:
                subprocess.run(
                    ["git", "checkout", branch], capture_output=True, check=True
                )
            subprocess.run(
                ["git", "pull"], capture_output=True, check=True
            )  # get the latest code from github

        used_clones.append(repo_dir)

        # with --github, -u and -c are applied after GitHub users are combined
        last_parser = GitLogsParser(
            repo=repo_dir,
            start=args.start,
            end=args.end,
            username=None if args.github else args.user,
            exclusions=args.exclusions,
            verbose=args.verbose,
            clean=False if args.github else args.clean,
        )
        rows = last_parser.parse()
        if args.github:
            rows = github_rows(
                last_parser, rows, repo_url, last_parser.get_identities(), args
            )
        all_results.extend(rows)  # collect across repos

    # emit a single table (or JSON array) covering all repositories
    if last_parser is not None:
        # an empty CSV table still gets the columns it would have had
        if args.aggregate:
            # OUT-6: one row per developer or per repository
            all_results = aggregate.aggregate(all_results, args.aggregate, args.github)
            fieldnames = aggregate.fieldnames(args.aggregate, args.github)
        elif args.github:
            fieldnames = (
                FIELDNAMES + GITHUB_FIELDNAMES + EMAIL_FIELDNAMES + ACTIVITY_FIELDNAMES
            )
        else:
            fieldnames = None
        output = last_parser.format_results(all_results, args.format, fieldnames)
        # end with exactly one newline: CSV and Markdown output already has one
        print(output, end="" if output.endswith("\n") else "\n")

    # REPO-5: only now that the results are out, delete the clones. Leave the
    # clone we were last inside first, so the deletion never depends on it.
    if args.clobber:
        sys.stdout.flush()
        os.chdir(start_dir)
        remove_clones(repos_dir, used_clones, args.verbose)


# if this script is being run directly...
if __name__ == "__main__":
    main()
