from boto.ec2.connection import EC2Connection
from boto.iam import IAMConnection

from audit import audit_log, real_username
#import sqlite3
from pysqlite2 import dbapi2 as sqlite3
import datetime

import simplejson

import re

import random

import exceptions

from myec2 import get_root_ec2_connection, get_root_IAM_connection

# Security note: need to disable debug logging to end-user so they
# won't see our "real" access key/secret access key

from cs61cpaths import USER_DB_FILE

dbh = sqlite3.connect(USER_DB_FILE, isolation_level=None)

def init_db():
    dbh.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_name TEXT PRIMARY KEY,
            create_time TEXT,
            create_account TEXT,
            login_password TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS access_keys (
            user_name TEXT REFERENCES users(user_name) ON DELETE CASCADE,
            access_key TEXT PRIMARY KEY,
            secret_access_key TEXT
        );
        CREATE TABLE IF NOT EXISTS ssh_keys (
            user_name TEXT REFERENCES users(user_name) ON DELETE CASCADE,
            key_name TEXT PRIMARY KEY,
            private_key TEXT,
            fingerprint TEXT
        );
    """)

root_creds = None

INSTANCE_COST = {
    'm1.small': 1,
    'm1.large': 4,
    'm1.xlarge': 8,
    't1.micro': .2,
    'm2.xlarge': 5.9,
    'm2.2xlarge': 11.8,
    'm2.4xlarge': 23.6,
    'c1.medium': 2,
    'c1.xlarge': 8,
    'cc1.4xlarge': 18.8
}
SPOT_BASE = .086

SPEND_LIMIT = 60

def user_exists(user_name):
    found_user = False
    for row in dbh.execute("""
SELECT 1 FROM users WHERE user_name = ?
""", [user_name]):
        found_user = True
    return found_user

class User: 
    def __init__(self, user_name):
        self.user_name = user_name
        self.access_keys = []
        self.init_access_keys()

    def proxy_port_base(self):
        end = self.user_name[-2:]
        value = (ord(end[0]) - ord('a')) * 26 + (ord(end[1]) - ord('a'))
        return value * 3 + 40000

    def get_password(self):
        for row in dbh.execute("""
    SELECT login_password FROM users WHERE user_name = ?
""", [self.user_name]):
            return str(row[0])
        return None

    def set_password(self, new_password):
        iam_root.update_login_profile(user_name, new_password)
        dbh.execute("BEGIN EXCLUSIVE")
        dbh.execute("""UPDATE users WHERE user_name = ? SET login_password = ?""",
            [self.user_name, new_password])
        dbh.execute("COMMIT")

    def init_access_keys(self):
        self.access_keys = []
        for row in dbh.execute("""
    SELECT access_key, secret_access_key FROM access_keys WHERE user_name = ?
""", [self.user_name]):
            self.access_keys.append({
                'key': str(row[0]),
                'secret_key': str(row[1]),
            })
        if len(self.access_keys) > 0:
            self.init_iam()
            self.init_ec2()

    def init_iam(self):
        self.iam = IAMConnection(
            aws_access_key_id = self.access_keys[0]['key'],
            aws_secret_access_key = self.access_keys[0]['secret_key'],
            debug = 0
        )

    def init_ec2(self):
        self.ec2 = EC2Connection(
            aws_access_key_id = self.access_keys[0]['key'],
            aws_secret_access_key = self.access_keys[0]['secret_key'],
            debug = 0
        )

    def get_access_keys(self):
        return self.access_keys

    def create_access_key(self): 
        iam_root = get_root_IAM_connection()
        response = iam_root.create_access_key(self.user_name)
        audit_log("Creating access key %s for %s" % (
            self.user_name, response.access_key_id
        ))
        dbh.execute("BEGIN EXCLUSIVE")
        dbh.execute("""
            INSERT OR IGNORE INTO access_keys (
                user_name,
                access_key,
                secret_access_key
            ) VALUES (?, ?, ?) 
        """, [self.user_name, 
              str(response.access_key_id), str(response.secret_access_key)])
        dbh.execute("COMMIT")
        self.init_access_keys()

    def get_ssh_keys(self):
        keys = {}
        for row in dbh.execute("""
            SELECT key_name, private_key, fingerprint
                FROM ssh_keys WHERE user_name = ?
        """, [self.user_name]):
            keys[str(row[0])] = {
                'private_key': str(row[1]),
                'fingerprint': str(row[2])
            }
        return keys

    def create_ssh_key(self, key_name):
        key_name = re.sub(r'[^-a-zA-Z0-9_]', '', key_name)
        if not key_name.startswith("%s-" % (self.user_name)):
            full_name = "%s-%s" % (self.user_name, key_name)
        else:
            full_name = key_name
        ec2 = get_root_ec2_connection()
        keypair = ec2.create_key_pair(
            key_name = full_name
        )
        audit_log("Creating SSH keypair %s for %s" % (
            full_name, self.user_name
        ))
        dbh.execute("BEGIN EXCLUSIVE")
        dbh.execute("""
            INSERT OR REPLACE INTO ssh_keys
                (user_name, key_name, private_key, fingerprint)
            VALUES (?, ?, ?, ?)
        """, [self.user_name, full_name, keypair.material, keypair.fingerprint])
        dbh.execute("COMMIT")

    def delete_ssh_key(self, key_name):
        if key_name in self.get_ssh_keys():
            ec2 = get_root_ec2_connection()
            ec2.get_key_pair(key_name).delete
            audit_log("Delete SSH key %s" % (key_name))
            dbh.execute("BEGIN EXCLUSIVE")
            dbh.execute("""
                DELETE FROM ssh_keys WHERE key_name=? AND user_name=?
            """, [key_name, self.user_name])
            dbh.execute("COMMIT")

    def delete_access_key(self, access_key):
        self.init_iam
        self.init_access_keys
        key_names = filter(lambda x: x['key'] == access_key, self.access_keys)
        iam = get_root_IAM_connection()
        if len(key_names):
            iam.delete_access_key(access_key, self.user_name)
            audit_log("Deleted access key %s" % (access_key))
            dbh.execute("BEGIN EXCLUSIVE")
            dbh.execute("""
                DELETE FROM access_keys WHERE access_key=? AND user_name=?
            """, [access_key, self.user_name])
            dbh.execute("COMMIT")

    def running_instances(self): 
        all_instances = self.ec2.get_all_instances(filters={ 'key-name': "%s*" % (self.user_name) })
        key_prefix = "%s-" % (self.user_name)
        result = []
        for reservation in all_instances:
            for instance in reservation.instances:
                instance.groups = map(lambda x:x.id, reservation.groups)
                if instance.key_name.startswith(key_prefix):
                    result += [instance]
        return filter(lambda x:x.state != "terminated",result)

    def running_spot_requests(self):
        use_filter = {'launch.key_name': "%s*" % (self.user_name)}
        requests = self.ec2.get_all_spot_instance_requests(filters=use_filter)
        key_prefix = "%s-" % (self.user_name)
        relevant = filter(lambda x:x.launch_specification.key_name.startswith(key_prefix), requests)
        return filter(lambda x:x.state == "open",relevant)

    def cost_instances(self):
        instances = self.running_instances()
        return sum(map(lambda x: INSTANCE_COST[x.instance_type], instances))

    def cost_proposal(self, instance_type, num_instances):
        return INSTANCE_COST[instance_type] * num_instances

    def run_instances(self, instance_info):
        info_without_ud = instance_info.copy()
        if 'user_data' in info_without_ud:
            del info_without_ud['user_data']
        old_cost = self.cost_instances()
        extra_cost = self.cost_proposal(
            instance_info['instance_type'],
            instance_info['count']
        )
        if not instance_info['key_name'].startswith(self.user_name):
            audit_log("Rejecting instance request %s (for %s) because of key" % (self.user_name, info_without_ud))
            raise Exception("Needs to be associated with SSH key")
        if old_cost + extra_cost > SPEND_LIMIT:
            audit_log("Rejecting instance request %s (for %s) because of cost" % (self.user_name, info_without_ud))
            raise Exception("Excessive instance cost")
        ec2 = get_root_ec2_connection()
        audit_log("Making instance requset %s for %s" % (
            info_without_ud, self.user_name
        ))
        if instance_info['use_spot']:
            spot_price = INSTANCE_COST[instance_info['instance_type']] * SPOT_BASE
            spot_requests = ec2.request_spot_instances(
                price=spot_price,
                image_id=instance_info['image_id'],
                count=instance_info['count'],
                key_name=instance_info['key_name'],
                security_groups=instance_info['security_groups'],
                user_data=instance_info.get('user_data'),
                instance_type=instance_info['instance_type'],
                placement=instance_info.get('availability_zone', None)
                #, availability_zone_group=instance_info.get('placement_group', None)
            )
            return spot_requests
        else:
            reservation = ec2.run_instances(
                image_id=instance_info['image_id'],
                min_count=instance_info['count'],
                max_count=instance_info['count'],
                key_name=instance_info['key_name'],
                security_groups=instance_info['security_groups'],
                user_data=instance_info['user_data'],
                instance_type=instance_info['instance_type'],
                placement=instance_info.get('availability_zone', None)
                #, placement_group=instance_info.get('placement_group', None)
            )
            return reservation

def get_user_policy(user_name):
    # Might need modification to support non-class-account names.
    return """
        {
            "Statement":[{
                "Effect":"Allow",
                "Action":[
                    "s3:*"
                ],
                "Resource": "arn:aws:s3:::cs61c/%(user_name)s*"
            },
            {
                "Effect":"Allow",
                "Action":[
                    "iam:*AccessKey*",
                    "iam:*SigningCert*",
                    "iam:*LoginProf*"
                ],
                "Resource": "arn:aws:iam::*:user/*%(user_name)s*"
            }]
        }
    """ % { 'user_name': user_name }

def iam_delete_user(iam_root, user_name):
    try:
        # ensure user exists before continuing
        auditlog("Trying to delete user %s" % (user_name))
        old_user_info = iam_root.get_user(user_name)

        # delete group associations, keys, signing certs, polciies for user
        for policy_name in iam_root.get_all_user_policies(user_name)['list_user_policies_response']['list_user_policies_result']['policy_names']:
            iam_root.delete_user_policy(user_name, policy_name)
        for group in iam_root.get_groups_for_user(user_name)['list_user_groups_response']['list_user_groups_result']:
            iam_root.remove_user_from_group(group['group_name'], user_name)
        # delete these credentials after we preventthem from being used to create
        # more user credentials
        for signing_cert in iam_root.get_all_signing_certs(user_name=user_name)['list_signing_certificates_response']['list_signing_certificates_result']['certificates']:
            iam_root.delete_signing_cert(signing_cert['certificate_id'], user_name)
        for access_key in iam_root.get_all_access_keys(user_name=user_name)['list_access_keys_response']['list_access_keys_result']['access_key_metadata']:
            iam_root.delete_access_key(access_key['access_key_id'], user_name)
    except StandardError, e:
        pass

def random_password():
    s = ""
    LETTERS = "abcdefghijkmnopqrstuvwxyz023456789ABCDEFGHJKLMNOPQRSTUVWXYZ"
    for i in xrange(8):
        s.append(random.choice(LETTERS))
    return s

def delete_user(user_name):
    iam_delete_user(get_root_IAM_connection(), user_name)
    dbh.execute("BEGIN EXCLUSIVE")
    dbh.execute("""DELETE FROM users WHERE user_name = ?""", [user_name])
    dbh.execute("COMMIT")

def make_user(user_name):
    audit_log("Creating user %s" % (user_name))
    iam_root = get_root_IAM_connection()
    iam_delete_user(iam_root, user_name)
    iam_root.create_user(user_name)
    iam_root.add_user_to_group("students", user_name)
    iam_root.put_user_policy(
        user_name,
        "%s-user" % (user_name),
        simplejson.dumps(simplejson.loads(get_user_policy(user_name)))
    )
    password = random_password()
    iam_root.create_login_profile(user_name, password)
    now = datetime.datetime.utcnow().isoformat()
    dbh.execute("BEGIN EXCLUSIVE")
    dbh.execute("""
        INSERT OR REPLACE INTO users (user_name, create_time, create_account, login_password)
            VALUES (?, ?, ?, ?)
    """, [user_name, now, real_username(), password])
    dbh.execute("COMMIT;")
    user = User(user_name)
    return user
