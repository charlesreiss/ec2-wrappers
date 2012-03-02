These are very raw, hard to use scripts we used to do EC2 stuff for CS61C at
UC Berkeley in the Fall 2010/Spring 2011 semesters. They are intended to
interface with Berkeley instructional infrastructure and have non-trivial setup.
These assume a shared Unix environment, with a privalleged account to run
setuid scripts and manage the actual EC2 credentials. They assume particular
account names. A cronjob running as the privalleged account is also required
for monitoring and accounting. Data is kept in two SQLite databases. (Keeping
these databases on an shared filesystem is probably a bad idea due to flaky
locking support.)

These scripts require an appropriate configured EC2 instance (not provided).
After the EC2 instance is booted, a script lie one in 
ec2-wrappers/hadoop/cloud/data will be run. To minimize setup times, it is best
if the EC2 instance has all software preinstalled.

Because these scripts can spend Real Money, I strongly recommend against
deploying them without understanding what they do reasonably well.

Because of their age, they have some dependencies on things which are
out-of-date. Most notably, we have a modified version of the Cloudera python
scripts for launching clusters on EC2, which are now deprecated in favor Apache
Whirr, which we have not adopted.

Most of the work in thie stuff labelled ec2-wrappers. These have three parts:

- Tools for managing IAM (aws.amazon.com/iam) identities for student accounts.
  These include creating various configuration files (containing credentials for
  the "identity" ~~ subaccount) in student home directories. 

- Tools for launching instances. We don't allow IAM identities to launch
  instances directly. As of this writing, IAM only allows us to set permissions
  to enable/disable instance launching entirely for an identity; we cannot set
  limits on how many instances an identity can launch. We set limits on
  instances that can be launched by controlling the user account. These scripts
  DO NOT attempt to stop instances that are left running for an excessive period
  of time, which is the *most common cause of excessive spending*. For
  accountability, each instance is marked with an SSH key named after the
  student account in question.

- Tools for accounting usage. In addition to keeping an audit log, a cronjob is
  included to query instance usage. Instance visiblity is logged into a database
  and a tool is provided for querying historical usage. Note that these scripts
  do not handle instances terminating and the cronjob not running soon enough to
  see the instance in the terminated state. (They will consider these instances
  still running.)

Files included in ec2-wrappers:

- cs61cpaths.py
  Configuration file for locations of things, including the root access key.

-	boto*
		copies of Boto (boto.cloudhackers.com), a Python library for
  interfacing with cloud providers that you probably want to use
  regardless. (You would probably want to grab a more recent copy.)

-	subaccounts.py
		python library for managing an SQLite database of IAM
(aws.amazon.com/iam) "identities" and SSH keypairs for each student:

  - this manages SSH keypairs for the identities. Keypairs cannot actually
  be associated with a particular identity explicitly, so this is managed
  in a local database and by the requirement for keypair names to start
  with the student's account name.
  - the IAM identities gives students identities (which have associated
  AWS credentials) which have permissions to do pretty much everything but
  launch instances and write all over S3 -- see 'student-policy'
  (configured by setup.sh in the same directory) + the extra policy
  returned by get_user_policy()
  - this code contains logic for launching instances of behalf of students
  (run_instances() method). This is called by ec2_runner.py

- ec2_util.py
  frontend program for interfacing subaccounts.py for students to create
  identities and rotate credentials for those identities.

- ec2_runner.py
  wrapper which hadoop-ec2 was modified to use to launch instances.
  Primarily intended to take an instance description in JSON from stdin
  and launch it. Run through a setuid trap.

- usage_cron.py (cron entrypoint), usage_report.py (command-line entrypoint), record_usage.py (library)
      take snapshots of active instances in an SQLite database and report on
  the estimated spend (only from instance hours running). Note that this
  does not behave well if it misses an instance termination (it will
  assume an instance is still running if it disppears from its snapshots
  of 'ec2-describe-instances' without being marked as 'terminated' first).

- setuid_wrap.c
        C wrapper code intended to be setuid. Expects to be compiled with
  -DREAL_EXECUTABLE. Probably should also make sure fd 0/1/2 are opened
  (e.g. by opening /dev/null three times) before calling the executable
  for extra paranoia.


Other directories:

- microproxy:
    Lightweight HTTP reverse proxy for use on instances to allow use of
    non-global addresses..
