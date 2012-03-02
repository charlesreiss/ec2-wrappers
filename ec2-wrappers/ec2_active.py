#!/usr/bin/python

import subaccounts
import audit
from optparse import OptionParser
import iso8601
import sys

def running_time(start_time):
    now = datetime.datetime.utcnow()
    return str(now - iso8601.parse_date(start_time))

INSTANCE_FORMAT = "%(id)-13s %(type)-8s %(time)15s %(host)40s %(group)20s"
SPOT_FROMAT = "%(id)-13s %(type)-8s %(time)15s"

parser = OptionParser()
parser.add_option('--terminate-all', action='store_true', default=False)
parser.add_option('--cancel-spot-requests', action='store_true', default=False)
(options, args) = parser.parse_args(sys.argv[1:])
opt = vars(options)

user = subaccounts.User(audit.real_username())

instances = user.running_instances()
spot_requests = user.running_spot_requests()

have_any = instances or spot_requests

print "Username: %s" % (audit.real_username())
if len(instances):
    print "Running EC2 Instances:"
    print INSTANCE_FORMAT % {
        'id': "INSTANCE-ID",
        'type': 'INSTANCE-TYPE',
        'time': 'RUNNING FOR', 
        'host': 'PUBLIC HOSTNAME',
        'ip': 'INTERNAL IP',
        'group': 'SECURITY GROUPS'
    }
    for instance in instances:
        print INSTANCE_FORMAT % {
            'id': instance.id,
            'type': instance.instance_type,
            'time': running_time(instance.launch_time),
            'host': instance.public_dns_name,
            'ip': instance.private_ip_address,
            'group': ','.join(map(str,instance.groups))
        }

    print "%d instances CURRENTLY running." % (len(instances))
else:
    print "No EC2 instances running."

if len(spot_requests):
    print "Pending spot instance requests:"
    print SPOT_FORMAT % {
        'id': 'REQUEST-ID',
        'type': 'INSTANCE-TYPE',
        'time': 'TIME PENDING'
    }
    for request in spot_requests:
        print SPOT_FORMAT % {
            'id': request.id,
            'type': request.launch_specification.instance_type,
            'time': running_time(request.create_time)
        }
    print "%d spot requests pending." % (len(instances))

if opt['cancel_spot_requests'] or opt['terminate_all']:
    for request in spot_requests:
        spot_request.cancel()
        print "Cancelled %s" % (request.id)
    have_any = False

if opt['terminate_all']:
    for instance in instances:
        instance.terminate()
        print "Terminated %s" % (request.id)
    have_any = False

if have_any:
    print "Run '%s --terminate-all' to terminate all EC2 instances and cancel all spot requests."
    print "Run 'ec2-terminate-instance INSTANCE-ID' to terminate a particular instance."
    if len(spot_requests):
        print "Run '%s --cancel-spot-requests' to cancel all spot requests."
        print "Run 'ec2-cancel-spot-requset REQUEST-ID' to cancel a particular spot request."
        print "(Remember to double-check that no instances started before you cancelled"
        print " the spot instance request; cancelling the request doesn't kill started "
        print " instances.)"
