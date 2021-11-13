# get all the repositories we will be tracking
#mapfile -t repos < repos.txt #only works in bash > 4.0
repos=()
while IFS= read -r line || [[ "$line" ]]; do
  repos+=("$line")
done < repos.txt

# get the before and after dates as first and second command-line arguments
# these dates must be one before and one after the intended date range
AFTER_DATE=$1
BEFORE_DATE=$2
OUTPUT_FILE_NAME=$3

function get_project_name {
	# split the repository URL by slashes
	IFS='/' read -ra path_components <<< "$1"
	# get the last part of the URL
	#DIR_NAME=${components[-1]} # bash >= version 4.1
	DIR_NAME=${path_components[${#path_components[@]}-1]} # bash < version 4.1

	# remove the .git extension
	IFS='.' read -ra DIR_NAME <<< "$DIR_NAME"
	# get the part before the extension
	DIR_NAME=${DIR_NAME[0]} # bash < version 4.1
}

# # loop through each repository and clone, if necessary
# echo ""
# echo "-- PULLING LATEST CODE FROM REPOSITORIES --"
for repo in ${repos[*]}; do

	# call the function to get the repo's directory name
	get_project_name $repo

	# check whether the directory already exists
	if [ -d "$DIR_NAME" ]; then
    	echo "PROJECT $DIR_NAME..."
    	# pull latest from origin
    	cd repos/$DIR_NAME
    	git pull
    	cd ../..
    else
    	echo "PROJECT $DIR_NAME..."
    	# clone repo
    	git clone $repo repos/$DIR_NAME
	fi

done

# loop through each repository and get contribution stats
# echo ""
# echo "-- GETTING CONTRIBUTION STATS FROM REPOSITORIES --"
# echo "" > $OUTPUT_FILE_NAME
echo "username,merges,commits,additions,deletions" > $OUTPUT_FILE_NAME
for repo in ${repos[*]}; do

	# call the function to get the repo's directory name
	get_project_name $repo

	#echo "PROJECT $DIR_NAME..."

	# run bash script to generate stats
	#echo "./git_activity.sh $DIR_NAME $AFTER_DATE $BEFORE_DATE"
	# ./git_activity.sh repos/$DIR_NAME $AFTER_DATE $BEFORE_DATE
	./git_activity_csv.sh repos/$DIR_NAME $AFTER_DATE $BEFORE_DATE >> $OUTPUT_FILE_NAME

done