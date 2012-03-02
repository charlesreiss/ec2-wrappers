#!/usr/bin/python
import subaccounts
import audit
import simplejson
import sys
import random
import getpass

from optparse import OptionParser

parser = OptionParser()
parser.add_option('--init', action='store_true', default=False)
parser.add_option('--create-ssh-key', action='store_true', default=False)
parser.add_option('--delete-ssh-key', action='store_true', default=False)
parser.add_option('--key-name', default=None)
parser.add_option('--rotate-secret', action='store_true', default=False)
parser.add_option('--list', action='store_true', default=False)
parser.add_option('--dump-ssh-key', action='store_true', default=False)
parser.add_option('--delete-account', action='store_true', default=False)
parser.add_option('--show-password', action='store_true', default=False)
parser.add_option('--set-password', action='store_true', default=False)
(options, args) = parser.parse_args(sys.argv[1:])
opt = vars(options)

REAL_USERNAME = audit.real_username()

if not REAL_USERNAME.startswith("cs61c"):
   raise Error("Only for CS61C accounts")

need_config_setup = False
need_initial_keys = False
user = None

if opt['delete_account']:
    print "Deleting EC2 account..."
    subaccounts.delete_user(REAL_USERNAME)
    if !opt['init']:
        sys.exit(0)
    
if opt['init']:
    if not subaccounts.user_exists(REAL_USERNAME):
        print "Creating account...",
        user = subaccounts.make_user(REAL_USERNAME)
        print "done"
        need_initial_keys = True
    else:
        print "Using existing account."

    need_config_setup = True

if user is None:
    user = subaccounts.User(REAL_USERNAME)

key_name = opt.get('key_name') or ('%s-default' % (REAL_USERNAME))

if not key_name.startswith(REAL_USERNAME):
    key_name = "%s-%s" % (REAL_USERNAME, key_name)

if opt['show_password'] or need_initial_keys:
    print "AWS profile pasword " % (user.get_password())

if opt['set_password']:
    new_pass = getpass.getpass("New password: ")
    new_pass_confirm = getpass.getpass("Confirm new password: ")
    if new_pass != new_pass_confirm:
        print "Passowrds don't match."
    else:
        user.set_password(new_pass)

if opt['create_ssh_key'] or need_initial_keys:
    if opt['delete_ssh_key']:
        parser.error("Can't delete and create SSH key at same time")
    print "Creating SSH key %s" % (key_name)
    user.create_ssh_key(key_name)

if opt['delete_ssh_key']:
    key_name = opt['key_name']
    print "Deleting SSH key %s" % (key_name)
    user.delete_ssh_key(key_name)

if opt['dump_ssh_key'] or need_initial_keys or need_config_setup:
    all_keys = user.get_ssh_keys()
    if key_name in all_keys:
        print "Dumping SSH key %s to $HOME/%s.pem" % (key_name, key_name)
        fh = audit.safe_open_write("%s/%s.pem" % (audit.home(), key_name), may_overwrite=True)
        fh.write(all_keys[key_name]['private_key'])
        fh.close()

if opt['rotate_secret'] or need_initial_keys:
    for access_key in user.get_access_keys():
        print "Deleting access key %s" % (access_key['key'])
        user.delete_access_key(access_key['key'])
    user.create_access_key()

if opt['list'] or need_initial_keys or opt['rotate_secret']:
    for access_key in user.get_access_keys():
        print "Your AWS access key is %s" % (access_key['key'])
        print "Your AWS secret access key is %s" % (access_key['secret_key'])

if opt['list'] or need_initial_keys:
    for (key_name, key_info) in user.get_ssh_keys().iteritems():
        print "SSH Key %s (fingerprint %s)" % (
            key_name, key_info['fingerprint']
        )

def random_availability_zone():
    return random.sample(["us-east-1a","us-east-1b","us-east-1c","us-east-1d"],1)

if need_config_setup:
    primary_access_key = user.get_access_keys()[0]
    fh = audit.safe_open_write("%s/ec2-environment.sh" % (audit.home()), may_overwrite=True)
    fh.write(
"""# Run this file with source or '.'
AWS_ACCESS_KEY_ID=%(access_key)s
AWS_SECRET_ACCESS_KEY=%(secret_key)s
JAVA_HOME=${JAVA_HOME-/Library/Java/Home}
AWS_IAM_HOME=/home/ff/cs61c/aws/IAMCli
AWS_CREDENTIAL_FILE=%(home)s/.aws-creds
EC2_PRIVATE_KEY=%(home)s/.aws-cert-private.pem
EC2_CERT=%(home)s/.aws-cert-public.pem
export AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY
export JAVA_HOME
export AWS_IAM_HOME
export AWS_CREDENTIAL_FILE
export EC2_PRIVATE_KEY
export EC2_CERT

if [ ! -e $EC2_PRIVATE_KEY ]; then
    new-ec2-certificate
fi
""" % {
    'home': audit.home(),
    'access_key': primary_access_key['key'],
    'secret_key': primary_access_key['secret_key']
})
    fh.close
    fh = audit.safe_open_write("%s/.boto" % (audit.home()), may_overwrite=True)
    fh.write(
"""
[Credentials]
aws_access_key_id=%(access_key)s
aws_secret_access_key=%(secret_key)s
""" % {
    'access_key': primary_access_key['key'],
    'secret_key': primary_access_key['secret_key']
})
    fh = audit.safe_open_write("%s/.aws-creds" % (audit.home()), may_overwrite=True)
    fh.write(
"""
AWSAccessKeyId=%(access_key)s
AWSSecretKey=%(secret_key)s
""" % {
    'access_key': primary_access_key['key'],
    'secret_key': primary_access_key['secret_key']
})
    audit.safe_make_dir("%s/.hadoop-cloud" % (audit.home()))
    fh = audit.safe_open_write("%s/.hadoop-cloud/clusters.cfg" % (audit.home()), may_overwrite=True)
    if fh:
        fh.write(
"""
[%(username)s-testing]
image_id=ami-a28c7ccb
instance_type=m1.small
key_name=%(username)s-default
private_key=%(home)s/%(username)s-default.pem
ssh_options=-i %%(private_key)s -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
user_data_file=http://cs61c-hadoop-scripts.s3.amazonaws.com/configure-hadoop-script.sh
proxy_port=%(testing_proxy)d

[%(username)s-medium]
image_id=ami-a28c7ccb
instance_type=c1.medium
key_name=%(username)s-default
private_key=%(home)s/%(username)s-default.pem
ssh_options=-i %%(private_key)s -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
user_data_file=http://cs61c-hadoop-scripts.s3.amazonaws.com/configure-hadoop-script.sh
proxy_port=%(medium_proxy)d

[%(username)s-large]
image_id=ami-9c8c7cf5
instance_type=c1.xlarge
key_name=%(username)s-default
private_key=%(home)s/%(username)s-default.pem
ssh_options=-i %%(private_key)s -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
user_data_file=http://cs61c-hadoop-scripts.s3.amazonaws.com/configure-hadoop-script.sh
proxy_port=%(large_proxy)d

""" % {
    'username': REAL_USERNAME,
    'home': audit.home(),
    'testing_proxy': user.proxy_port_base(),
    'medium_proxy': user.proxy_port_base() + 1,
    'large_proxy': user.proxy_port_base() + 2,
    'zone_testing': random_availability_zone()[0],
    'zone_medium': random_availability_zone()[0],
    'zone_large': random_availability_zone()[0]
})
        fh.close()

    fh = audit.safe_open_write("%s/.s3cfg" % (audit.home()), may_overwrite=True)
    fh.write(
"""
[default]
access_key=%(access_key)s
secret_key=%(secret_key)s
host_base=s3.amazonaws.com
host_bucket=%%(bucket)s.s3.amazonaws.com
bucket_location=US
use_https=True
encrypt=False
force=False
""" % {
    'access_key': primary_access_key['key'],
    'secret_key': primary_access_key['secret_key']
}
    )
    fh.close()

