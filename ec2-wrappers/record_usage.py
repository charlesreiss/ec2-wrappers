from myec2 import get_root_ec2_connection
import datetime
import simplejson
#import sqlite3
from pysqlite2 import dbapi2 as sqlite3

from cs61cpaths import USAGE_DB_FILE

dbh = sqlite3.connect(USAGE_DB_FILE, isolation_level=None)

# BUG: pending_instance_times doesn't deal with now-stopped instances correctly

def init_db():
    dbh.executescript("""
        CREATE TABLE IF NOT EXISTS instances (
            instance_id TEXT PRIMARY KEY,
            instance_type TEXT NOT NULL,
            start_time REAL,
            end_time REAL DEFAULT NULL,
            last_seen TEXT,
            is_spot BOOLEAN,
            username TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS instance_stopped (
            instance_id TEXT REFERENCES instances,
            stopped_time REAL,
            running_time REAL DEFAULT NULL,
            PRIMARY KEY(instance_id, stopped_time)
        );

        CREATE TABLE IF NOT EXISTS pending_spot_requests (
            request_id TEXT PRIMARY KEY,
            instance_type TEXT NOT NULL,
            request_time REAL,
            username TEXT NOT NULL
        );

        CREATE VIEW IF NOT EXISTS instance_stopped_time AS
            SELECT
                instance_id,
                SUM(hours) AS hours
            FROM (
                SELECT
                    instance_id,
                    (running_time - stopped_time)*24 AS hours
                        FROM instance_stopped WHERE stopped_time IS NOT NULL
            )
            GROUP BY instance_id;

        CREATE VIEW IF NOT EXISTS finished_instance_times AS
            SELECT
                instances.instance_id AS instance_id,
                instance_type,
                round(24*(instances.end_time - instances.start_time) - 
                    ifnull(instance_stopped_time.hours, 0) + .5) AS hours,
                is_spot,
                username
                FROM instances LEFT OUTER JOIN instance_stopped_time
                    ON instances.instance_id = instance_stopped_time.instance_id
                WHERE instances.end_time IS NOT NULL;

        CREATE VIEW IF NOT EXISTS pending_instances AS
            SELECT instance_id, instance_type, start_time, is_spot, username FROM instances
                WHERE instances.end_time IS NULL;

        CREATE VIEW IF NOT EXISTS pending_instance_times AS
            SELECT
                instances.instance_id AS instance_id,
                instance_type,
                round(24*(julianday('now') - instances.start_time) - 
                    ifnull(instance_stopped_time.hours, 0) + .5) AS hours,
                is_spot,
                username
                FROM instances LEFT OUTER JOIN instance_stopped_time
                    ON instances.instance_id = instance_stopped_time.instance_id
                WHERE instances.end_time IS NULL;
    """)

def user_from_key(key_name): 
    if key_name.startswith("cs"):
        return "-".join(key_name.split("-")[0:2])
    else:
        return key_name.split("-")[0]

def update_instances(username = None):
    ec2 = get_root_ec2_connection()
    use_filter = None
    if username:
        use_filter = { 'key-name': "%s*" % username }
    all_instances = ec2.get_all_instances(filters=use_filter)
    now = datetime.datetime.utcnow().isoformat()
    for reservation in all_instances:
        for instance in reservation.instances:
            # We can safely import each instance as a transaction.
            dbh.execute("BEGIN IMMEDIATE TRANSACTION")
            username = user_from_key(instance.key_name)
            start_time = instance.launch_time
            is_spot = instance.spot_instance_request_id != None
            if is_spot:
                is_spot = 1
            else:
                is_spot = 0
            old_end_time = None
            for row in dbh.execute("""
                SELECT end_time FROM instances WHERE instance_id = ?
            """, [instance.id]):
                old_end_time = row[0]
            old_stop_time = None
            for row in dbh.execute("""
                SELECT stopped_time FROM instance_stopped WHERE instance_id = ?
                    AND running_time IS NULL
            """, [instance.id]):
                old_stop_time = row[0]
            if instance.state == 'terminated' and old_end_time == None:
                dbh.execute("""
                    INSERT OR REPLACE INTO instances (
                        instance_id, instance_type, start_time, end_time,
                        last_seen, is_spot, username
                    ) VALUES (?, ?, julianday(?), julianday(?), julianday(?), ?, ?)
                """, [instance.id, instance.instance_type, start_time, now,
                      now, is_spot, username])
            if instance.state != 'stopped' and instance.state != 'terminated' and old_stop_time != None:
                dbh.execute("""
                    UPDATE instance_stopped WHERE
                        instance_id = ? AND stopped_time = ?
                    SET running_time = ?
                """, [instance.id, old_stop_time, now])
            if instance.state != 'terminated':
                dbh.execute("""
                    INSERT OR REPLACE INTO instances (
                        instance_id, instance_type, start_time,
                        last_seen, is_spot, username
                    ) VALUES (?, ?, julianday(?), julianday(?), ?, ?)
                    """, [instance.id, instance.instance_type,
                          start_time, now, is_spot, username])
            if instance.state == 'stopped':
                dbh.execute("""
                    INSERT INTO instance_stopped (instance_id, stopped_time)
                        VALUES (?, ?)
                """, [instance.id, now])

            dbh.execute("COMMIT")

def update_spot_requests(username=None):
    ec2 = get_root_ec2_connection()
    use_filter = None
    if username:
        use_filter = {'launch.key_name': "%s*" % (username)}
    requests = ec2.get_all_spot_instance_requests(filters=use_filter)

    dbh.execute("BEGIN IMMEDIATE TRANSACTION")
    if username:
        dbh.execute("""
            DELETE FROM pending_spot_requests WHERE username = ?
        """, [username])
    else:
        dbh.execute("""
            DELETE FROM pending_spot_requests
        """)

    for request in requests:
        username = user_from_key(request.launch_specification.key_name)
        instance_type = request.launch_specification.instance_type
        request_time = request.create_time
        if request.state == 'open':
            dbh.execute("""
                INSERT OR REPLACE INTO pending_spot_requests (
                    request_id, instance_type, request_time, username
                ) VALUES (?, ?, julianday(?), ?)
            """, [request.id, instance_type, request_time, username])
    
    dbh.execute("COMMIT")


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

COST_BASE = .085

SPOT_FACTOR = 0.7

def spot_to_type(is_spot):
    if is_spot:
        return "spot"
    else:
        return "demand"

def report_set(instance_hour_set):
    result = ""
    total = 0.0
    for (is_spot, instance_type, hours) in instance_hour_set:
        estimate = INSTANCE_COST[instance_type] * COST_BASE
        if is_spot:
            estimate *= SPOT_FACTOR
        subtotal = estimate * hours
        total += subtotal
        result += "%(hours)5d hours of %(type)10s (%(spot)s) @ $%(estimate)5.3f = $%(subtotal)6.3f\n" % {
            'hours': hours,
            'type': instance_type,
            'spot': spot_to_type(is_spot),
            'estimate': estimate,
            'subtotal': subtotal
        }
    if len(instance_hour_set) == 0:
        result += "(none)\n"
    result += "Total cost $%(total)6.3f\n" % { 'total': total }
    return (result, total)

def user_report(username, include_pending=True, include_live=True):
    username = "%s" % (username)
    if include_live:
        update_instances(username)
        update_spot_requests(username)

    finished_instances = dbh.execute("""
        SELECT is_spot, instance_type, SUM(hours) AS hours FROM
            finished_instance_times WHERE username = ?
            GROUP BY is_spot, instance_type
    """, [username]).fetchall()

    pending_instances = dbh.execute("""
        SELECT is_spot, instance_type, SUM(hours) AS hours FROM
            pending_instance_times WHERE username = ?
            GROUP BY is_spot, instance_type;
    """, [username]).fetchall()

    pending_spot_requests = dbh.execute("""
        SELECT
            1 AS is_spot, instance_type, COUNT(*) AS hours
            FROM pending_spot_requests 
            WHERE username = ? GROUP BY instance_type
    """, [username]).fetchall()


    total = 0.0
    result = ""
    if include_pending and len(pending_spot_requests):
        (description, subtotal) = report_set(pending_spot_requests)
        result += "Pending spot requests:\n%s" % (description)
        total += subtotal
    if include_pending and len(pending_instances):
        (description, subtotal) = report_set(pending_instances)
        result += "Running instances:\n%s" % (description)
        total += subtotal
    (description, subtotal) = report_set(finished_instances)
    result += "Finished instances:\n%s" % (description)
    total += subtotal
    
    return (result, total)

def users():
    return map(lambda x:x[0], dbh.execute("""
        SELECT DISTINCT username FROM instances
    """).fetchall())
    
