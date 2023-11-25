import os
import subprocess
import argparse
import datetime
import re
from .GitLogsParser import GitLogsParser


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
        help="The git username to report.  Default is all contributing users",
        default=None,
    )
    parser.add_argument(
        "-s", "--start", help="Start date in mm/dd/yyyy format", default=str_last_year
    )  # default to one year ago
    parser.add_argument(
        "-e", "--end", help="End date in mm/dd/yyyy format", default=str_today
    )  # default to today
    parser.add_argument(
        "-x",
        "--exclusions",
        help='A comma-separated string of files to exclude, e.g. --excusions "foo.zip, *.jpg, *.json" ',
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
        default=True,
        action="store_true",
    )
    args = parser.parse_args()

    # fix up exclusions
    args.exclusions = re.split(
        r",\s*", args.exclusions
    )  # split up comma-separated string into list
    #   print(f'Exclusions: {args.exclusions}')

    # deal with repofile, if specified
    repository_urls = [args.repository]
    if args.repofile:
        f = open(args.repofile, "r", encoding="utf8")
        repository_urls = [
            line for line in f.read().strip().split("\n")
        ]  # a list of urls from the file

    # navigate into the directory where repos will be stored
    repos_dir = os.path.join(
        os.getcwd(), "repos"
    )  # where we will clone the repos we will parse
    # make the directory where we will store the repos, if not present
    if not os.path.exists(repos_dir):
        os.makedirs(repos_dir)

    # loop through each git repository url
    for repo_url in repository_urls:
        os.chdir(repos_dir)  # start from the parent directory of all repos
        # code = subprocess.run(['pwd']) # check the directory

        repo_dir = GitLogsParser.repo_name_from_url(
            repo_url
        )  # extract the humanish repo name from the URL
        repo_dir = os.path.join(repos_dir, repo_dir)  # convert to absolute path
        # clone or pull the repo into the repo_dir
        if not os.path.exists(repo_dir):
            # has not yet been cloned... do a clone
            subprocess.run(
                ["git", "clone", repo_url], capture_output=True, check=True
            )  # clone the code from github
            os.chdir(repo_dir)  # navigate into this repository's directory
        else:
            # has previously been cloned... do a pull
            os.chdir(repo_dir)  # navigate into this repository's directory
            subprocess.run(
                ["git", "pull"], capture_output=True, check=True
            )  # clone the code from github

        git_logs_parser = GitLogsParser(
            repo=repo_dir,
            start=args.start,
            end=args.end,
            username=args.user,
            exclusions=args.exclusions,
            verbose=args.verbose,
            clean=args.clean,
        )
        results = git_logs_parser.parse()
        output = git_logs_parser.format_results(results, args.format)
        print(output)


# if this script is being run directly...
if __name__ == "__main__":
    main()
