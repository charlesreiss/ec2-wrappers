
export JAVA_HOME=/Library/Java/Home PATH=/home/ff/cs61c/aws/IAMCli:$PATH AWS_IAM_HOME=/home/ff/cs61c/aws/IAMCli AWS_CREDENTIAL_FILE=/home/ff/cs61c/ec2-data/iam-creds
iam-groupcreate -g students
iam-groupuploadpolicy -g students -p students -f student-policy
