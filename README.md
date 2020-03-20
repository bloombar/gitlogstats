# Git Developer Contributions Analysis

This repository contains tools to track individuals' contributions to a set of GitHub repositories within a particular time range.  GitHub's own Insights tools and charts are not extremely useful, and often omit contributors or give misleading statistics.

The bash scripts, when run, will iterate through a set of repositories and output the number of merges, commits, lines added and deleted, and files changed by each contributor to the repositories.

## Assumptions

1. You have cloned this repository to your local machine
1. You have entered a list of repositories you are interested in into the file named `repos.txt` - one repository URL on each line ... see example.
1. You have granted yourself execute permissions to all bash scripts file, e.g. `chmod u+x *.sh`.

## Example usage

### Multiple repository analytics
The script named `do_all.sh` loads an array of the remote URLs of repositories of interest from the file named `repos.txt`.

Let's say you would like to see each contributor's activity to all repositories for the period between March 3rd, 2020 and March 10th, 2020.  

```bash
./do_all.sh 3/2/2020 3/11/2020
```

Notice that the dates in the command must be one day before and one day after the desired beginning and end dates of interest.

### Single repository analytics
The script named `git_activity.sh` outputs analytics for a single repository.

The following code will output the activity of each contributor to a single repository.  Replace my_repository_directory_name with the directory containing a git repository.

```bash
./git_activity.sh repos/my_repository_directory_name 3/2/2020 3/11/2020
```

## Words of caution

### Large numbers of additions or deletions
If a particular user shows a very large number of additions or deletions, typically on the order of many hundreds or thousands, this could be a sign of poor usage of version control.

Most likely, the user has failed to update their version control settings to ignore platform or 3rd party code to (i.e. has not updated their `.gitignore` file prior to adding such code), and is therefore tracking additions/deletions of code that is not theirs.  The entire contribution for that user during this date range should be ignored in this case until the developer fixes this problem.

### Redundant usernames 
The output of the script sometimes lists the same individual contributor under more than one git username...  This is most likely due to different username settings for various git and GitHub clients.

If a single developer has multiple usernames that all show the same statistics, then only count those stats once.  Otherwise, if a single developer has multiple usernames that show different statistics, then add them together to come up with the total for that developer.

