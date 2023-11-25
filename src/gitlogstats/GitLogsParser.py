#!/usr/bin/env python3

import os

# import sys
import subprocess

# import argparse
import datetime
import shlex
import re
import json


class GitLogsParser:
    def __init__(
        self,
        repo,
        start,
        end,
        username,
        exclusions=[],
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
        self.exclusions = exclusions
        self.verbose = verbose
        self.clean = clean

        # go into the selected repository directory, if any
        if self.repository:
            self.verboseprint(f"Switching to: {self.repository}...")
            os.chdir(self.repository)

    def get_contributors(self):
        """
        Return a list of contributors to this repository.
        @returns: a list of all contributors' git usernames
        """
        contributors = set()  # a set that will include all contributors

        # use git logs to get all contributor usernames

        # split up the command so the subprocess module can run it
        cmd = "git log --format='%aN'".split(" ")
        with subprocess.Popen(
            cmd, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True
        ) as p:
            for line in p.stdout:
                line = line.strip().strip("'")  # remove line break and single quotes
                contributors.add(line)  # add to set

        contributors = list(contributors)  # list version
        contributors_string = ", ".join(contributors)  # string version
        self.verboseprint(f"Contributors: {contributors_string}...")
        return contributors

    def parse(self):
        """
        Parse the git logs and extract a breakdown of the contributions of each contributing user.
        @returns: contribution stats of all users, as a dictionary with usernames as the keys
        """

        # git requires start & end dates to be 1 day before and after the target range
        git_start_date = datetime.datetime.strptime(
            self.start, "%m/%d/%Y"
        ) - datetime.timedelta(days=1)
        git_end_date = datetime.datetime.strptime(
            self.end, "%m/%d/%Y"
        ) + datetime.timedelta(days=1)

        # get stats for each contributor
        stats = []  # will contain contribution stats for each contributor

        # if no contributor specified, get a list of all of them
        contributors = [self.username]  # liit to the specified username, if any
        if not self.username:
            contributors = list(
                self.get_contributors()
            )  # the full list of contributors

        for contributor in contributors:
            exclusions = "-- . " + " ".join(
                [f'":(exclude,glob)**/{x}"' for x in self.exclusions]
            )  # put the exclusions in the format git logs uses
            # exclusions = r'''-- . ":(exclude,glob)**/package-lock.json" ":(exclude,glob)**/*.jpg" ":(exclude,glob)**/*.png" ":(exclude,glob)**/*.gif" ":(exclude,glob)**/*.svg" ":(exclude,glob)**/*.pdf" ":(exclude,glob)**/*.zip" ":(exclude,glob)**/*.csv" ":(exclude,glob)**/*.json" '''
            cmd = f'git log --shortstat --author="{contributor}" --after="{git_start_date}" --before="{git_end_date}" {exclusions}'
            self.verboseprint(f"Running command: {cmd}")
            # self.verboseprint(f'With exclusions: {exclusions}')
            cmd = shlex.split(cmd)  # split command by spaces, except where in quotes
            result = subprocess.run(
                cmd, capture_output=True, check=True
            )  # run the command
            logs = result.stdout.decode("utf-8")  # capture the output
            # set up stats for this contributor in dictionary form
            entry = {
                "username": contributor,  # redundant, but useful
                "repository": self.repo_name_from_url(self.repository),
                "start_date": self.start,
                "end_date": self.end,
                # 'merges': len(re.findall('Merge', logs)), # number of times we find a merge message... git logs do not reliably show these
                "commits": len(
                    re.findall("commit [a-z0-9]+\n", logs)
                ),  # number of times we find a commit message
                "insertions": 0,
                "deletions": 0,
                "files": 0,
            }
            # find all number of files changed, lines inserted, lines deleted:
            pattern = re.compile(
                r"commit ([a-zA-Z0-9]+).*\nAuthor:\s(.*)\s<((.*))>.*\nDate:\s(.*)\n\n(.*)\n\n(.*?(\d+) file[s]? changed)?(.*?(\d+) insertion[s]?)?(.*?(\d+) deletion[s]?)?"
            )
            for match in re.finditer(pattern, logs):
                # print(str(match.groups()))
                entry["files"] += int(match.group(8)) if match.group(8) else 0
                entry["insertions"] += int(match.group(10)) if match.group(10) else 0
                entry["deletions"] += int(match.group(12)) if match.group(12) else 0
            # add this user's stats to the list
            # removing merges since they are not reliably mentioned in the stats
            # if(self.clean and (entry['merges'] == 0 and entry['commits'] == 0 and entry['insertions'] == 0 and entry['deletions'] == 0 and entry['files'] == 0)):
            if self.clean and (
                entry["commits"] == 0
                and entry["insertions"] == 0
                and entry["deletions"] == 0
                and entry["files"] == 0
            ):
                pass
            else:
                stats.append(entry)
            # self.verboseprint('Entry: ', entry) # only printed when in verbose mode
        return stats

    def format_results(self, results, output_format):
        """
        Format the parsed data in the selected format.
        @param results: A list of dictionaries, with each representing a contributor to the repository.
        @param output_format: The desired output format, e.g. 'csv', 'json', or 'markdown'
        """
        self.verboseprint(f"Outputting results in {output_format.upper()} format:...")
        output = ""
        # output in the selected format
        if output_format == "csv":
            if len(results) > 0:
                fieldnames = results[
                    0
                ].keys()  # get the field names from the first dictionary in the list
                output += ",".join(list(fieldnames)) + "\n"
            for entry in results:
                str_values = [str(val) for val in list(entry.values())]
                output += ",".join(str_values) + "\n"

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
                # each row of values
                str_values = [str(val) for val in list(entry.values())]
                output += "| " + " | ".join(str_values) + " |\n"

        return output

    def get_repository_urls(self):
        """
        Returns a list repository URLs to be analyzed.
        """
        repository_urls = [self.repository]
        if self.repofile:
            f = open(self.repofile, "r", encoding="utf8")
            repository_urls = [
                line for line in f.read().strip().split("\n")
            ]  # a list of urls from the file
            f.close()
        return repository_urls

    def verboseprint(self, *args):
        """
        Print out debugging info only if verbose mode has been turned on.
        """
        if self.verbose:
            v = print
        else:
            v = lambda *args: None
        v(*args)

    @staticmethod
    def repo_name_from_url(repo_url):
        """
        Extracts the humanish repository name from the full repository URL.  For example, 'foo-bar' from 'https://github.com/education-automation/foo-bar.git'
        @param repo_url: The URL of the repository of interest
        @returns: The repository name, with the rest of the URL removed.
        """
        repo_name = (
            repo_url.strip("/").split("/")[-1].split(".")[0]
        )  # get just the directory name from the url of this repo
        return repo_name
