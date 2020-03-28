#!/usr/bin/env bash

# this script assumes that you have already cloned a git repository and are currently in the parent directory of this repository directory
# get the directory name of the repository as the first command-line argument
REPO=$1

# get the before and after dates as second and third command-line arguments
# these dates must be one before and one after the intended date range
AFTER_DATE=$2
BEFORE_DATE=$3

if [ -z "$AFTER_DATE" ] || [ -z "$BEFORE_DATE" ] ; then
    echo Error: no before or after date specified for $REPO.
    exit 0
fi


# validate the arguments
#if ["$REPO" == ""] || ["$AFTER_DATE" == ""] || ["$BEFORE_DATE" == ""]; then
#	echo "usage: git_activity git_repo_directory after_date before_date"
#	echo "       git_repo_directory - a directory containing a local git repository"
#	echo "       after_date         - the day before the starting date of interest, e.g. 10/30/2019"
#	echo "       before_date        - the day after the ending date of interest, e.g. 12/1/2019"
#	echo ""
#	# quit
#	exit
#fi

# go into the selected repository directory
cd $REPO

# pull latest code from the repo
echo ""
echo "PROJECT $REPO between $AFTER_DATE and $BEFORE_DATE, exclusive"
git pull

# loop through each contributor
git log --format='%aN' | sort -u | while read user
do
	# show each contributor's stats
    printf '%-25s' "- $user -"
    echo -n $(git log --shortstat -- . ":(exclude)package-lock.json" --author="$user" --after="$AFTER_DATE" --before="$BEFORE_DATE" | grep -E "Merge" | awk '{merges+=1} END {printf "merges: %03d | ", merges}')
    echo -n $(git log --shortstat -- . ":(exclude)package-lock.json" --author="$user" --after="$AFTER_DATE" --before="$BEFORE_DATE" | grep -E "fil(e|es) changed" | awk '{commits+=1; files+=$1; inserted+=$4; deleted+=$6} END {printf " commits: %05d | additions: %05d | deletions: %05d | files: %05d", commits, inserted, deleted, files }')
    echo ""

done