#!/usr/bin/env python3

import os, sys, subprocess, argparse, datetime, shlex, re

class GitLogsParser:
    def __init__(self, repo, start, end, username, exclusions=[], repofile=None, verbose=False, clean=False):
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
            self.verboseprint('Switching to: {}...'.format(self.repository))
            os.chdir(self.repository)
        
    def get_contributors(self):
        """
        Return a list of contributors to this repository.
        @returns: a list of all contributors' git usernames
        """
        contributors = set() # a set that will include all contributors

        # use git logs to get all contributor usernames
        cmd = "git log --format='%aN'".split(' ') # split up the command so the subprocess module can run it
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True) as p:
            for line in p.stdout:
                line = line.strip().strip("'") # remove line break and single quotes
                contributors.add(line) # add to set

        contributors = list(contributors)
        self.verboseprint('Contributors: {}...'.format(', '.join(contributors)))
        return contributors

    def parse(self):
        """
        Parse the git logs and extract a breakdown of the contributions of each contributing user.
        @returns: contribution stats of all users, as a dictionary with usernames as the keys
        """

        # git requires start & end dates to be 1 day before and after the target range
        git_start_date = datetime.datetime.strptime(self.start, "%m/%d/%Y") - datetime.timedelta(days = 1)
        git_end_date = datetime.datetime.strptime(self.end, "%m/%d/%Y") + datetime.timedelta(days = 1)

        # get stats for each contributor
        stats = [] # will contain contribution stats for each contributor

        # if no contributor specified, get a list of all of them
        contributors = [self.username] # liit to the specified username, if any
        if not self.username:
            contributors = list(self.get_contributors()) # the full list of contributors
        
        for contributor in contributors:
            exclusions = '-- . ' + ' '.join(['":(exclude,glob)**/{}"'.format(x) for x in self.exclusions]) # put the exclusions in the format git logs uses
            # exclusions = r'''-- . ":(exclude,glob)**/package-lock.json" ":(exclude,glob)**/*.jpg" ":(exclude,glob)**/*.png" ":(exclude,glob)**/*.gif" ":(exclude,glob)**/*.svg" ":(exclude,glob)**/*.pdf" ":(exclude,glob)**/*.zip" ":(exclude,glob)**/*.csv" ":(exclude,glob)**/*.json" '''
            cmd = 'git log --shortstat --author="{contributor}" --after="{start}" --before="{end}" {exclusions}'.format(contributor=contributor, start=git_start_date, end=git_end_date, exclusions=exclusions)
            self.verboseprint('Running command: {}...'.format(cmd))
            cmd = shlex.split(cmd) # split command by spaces, except where in quotes
            result = subprocess.run(cmd, capture_output=True) # run the command
            logs = result.stdout.decode('utf-8') # capture the output
            # set up stats for this contributor in dictionary form
            entry = {
                'username': contributor, # redundant, but useful
                'repository': self.repo_name_from_url(self.repository),
                'start_date': self.start,
                'end_date': self.end,
                'merges (branch)': len(re.findall('Merge branch', logs)), # number of times we find a merge message
                'merges (non-branch)': len(re.findall('Merge:', logs)), # number of times we find a merge message
                'commits': len(re.findall('commit [a-z0-9]+\n', logs)), # number of times we find a commit message
                'insertions': 0,
                'deletions': 0,
                'files': 0
            }
            # find all number of files changed, lines inserted, lines deleted:
            pattern = re.compile('(\d*) files? changed.* (\d*) insertions?.* (\d*) deletions?.*\n')
            for match in re.finditer(pattern, logs):
                # print(str(match.groups()))
                entry['files'] += int(match.group(1))
                entry['insertions'] += int(match.group(2))
                entry['deletions'] += int(match.group(3))
            # add this user's stats to the list
            if(self.clean and (entry['merges'] == 0 and entry['commits'] == 0 and entry['insertions'] == 0 and entry['deletions'] == 0 and entry['files'] == 0)):
                pass
            else:
                stats.append(entry)
            # self.verboseprint('Entry: ', entry) # only printed when in verbose mode
        return stats

    def format_results(self, results, format):
        """
        Format the parsed data in the selected format.
        @param results: A list of dictionaries, with each representing a contributor to the repository.
        @param format: The desired output format, e.g. 'csv', 'json', or 'markdown'
        """
        self.verboseprint('Outputting results in {} format:...'.format(format.upper()))
        output = ''
        # output in the selected format
        if format == 'csv':
            if len(results) > 0:
                fieldnames = results[0].keys() # get the field names from the first dictionary in the list
                output += ','.join(list(fieldnames)) + '\n'
            for entry in results:
                str_values = [str(val) for val in list(entry.values())]
                output += ','.join(str_values) + '\n'

        elif format == 'json':
            import json
            output = json.dumps(results)

        elif format == 'markdown':
            if len(results) > 0:
                fieldnames = results[0].keys() # get the field names from the first dictionary in the list
                output += '| ' + ' | '.join(list(fieldnames)) + ' |\n' # headings
                output += '| ' + ' | '.join([':----' for key in results[0].keys()]) + ' |\n' # heading separator lines
            for entry in results:
                # each row of values
                str_values = [str(val) for val in list(entry.values())]
                output += '| ' + ' | '.join(str_values) + ' |\n'

        return output

    def get_repository_urls(self):
        repository_urls = [self.repository]
        if self.repofile:
            f = open(self.repofile, 'r')
            repository_urls = [line for line in f.read().strip().split('\n')] # a list of urls from the file
            f.close()
        return repository_urls

    def verboseprint(self, *args):
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
        repo_name = repo_url.strip("/").split("/")[-1].split(".")[0] # get just the directory name from the url of this repo
        return repo_name


# if this script is being run directly...
if __name__ == "__main__":
    # default dates
    today = datetime.date.today()
    str_today = today.strftime("%m/%d/%Y") # the date today in standard US format
    last_year = datetime.datetime.now() - datetime.timedelta(days = 365) # the the date one year ago from today
    str_last_year = last_year.strftime("%m/%d/%Y")

    # default files to exclude from analysis
    exclusions = ['package-lock.json', '*.jpg', '*.png', '*.gif', '*.svg', '*.pdf', '*.zip', '*.gz', '*.tar', '*.csv', '*.json']

    # get the command-line arguments
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-r", "--repository", help="the public URL of the repository whose logs to parse")
    group.add_argument("-rf", "--repofile", help="the path to simple text file with a list of repository URLs to parse")
    parser.add_argument('-u', '--user', help="The git username to report.  Default is all contributing users", default=None)
    parser.add_argument("-s", "--start", help="Start date in mm/dd/yyyy format", default=str_last_year) #default to one year ago
    parser.add_argument("-e", "--end", help="End date in mm/dd/yyyy format", default=str_today) #default to today
    parser.add_argument("-x", "--exclusions", help='A comma-separated string of files to exclude, e.g. --excusions "foo.zip, *.jpg, *.json" ', default=','.join(exclusions))
    parser.add_argument("-f", "--format", help="The format in which to output the results", default='csv', choices=['csv', 'json', 'markdown'])
    parser.add_argument("-v", "--verbose", help="Whether to output debugging info", default=False, action="store_true")
    parser.add_argument("-c", "--clean", help="Remove contributors without any contribuition", default=False, action="store_true")
    args = parser.parse_args()


    # fix up exclusions
    args.exclusions = re.split(r',\s*', args.exclusions) # split up comma-separated string into list
    # print(exclusions)

    # deal with repofile, if specified
    repository_urls = [args.repository]
    if args.repofile:
        f = open(args.repofile, 'r')
        repository_urls = [line for line in f.read().strip().split('\n')] # a list of urls from the file

    # navigate into the directory where repos will be stored
    repos_dir = os.path.join(os.getcwd(), 'repos') # where we will clone the repos we will parse
    # make the directory where we will store the repos, if not present
    if not os.path.exists(repos_dir):
        os.makedirs(repos_dir)

    # loop through each git repository url
    for repo_url in repository_urls:
        os.chdir(repos_dir) # start from the parent directory of all repos
        # code = subprocess.run(['pwd']) # check the directory

        repo_dir = GitLogsParser.repo_name_from_url(repo_url) # extract the humanish repo name from the URL
        repo_dir = os.path.join(repos_dir, repo_dir) # convert to absolute path        
        # clone or pull the repo into the repo_dir
        if not os.path.exists(repo_dir):
            # has not yet been cloned... do a clone
            subprocess.run(['git', 'clone', repo_url], capture_output=True) # clone the code from github
            os.chdir(repo_dir) # navigate into this repository's directory
        else:
            # has previously been cloned... do a pull
            os.chdir(repo_dir) # navigate into this repository's directory
            subprocess.run(['git', 'pull'], capture_output=True) # clone the code from github

        git_logs_parser = GitLogsParser(repo=repo_dir, start=args.start, end=args.end, username=args.user, verbose=args.verbose, clean=args.clean)
        results = git_logs_parser.parse()
        output = git_logs_parser.format_results(results, args.format)
        print(output)
        