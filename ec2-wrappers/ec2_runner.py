#!/usr/bin/python
import subaccounts
import audit
import sys
import simplejson
import base64

from optparse import OptionParser

REAL_USERNAME = audit.real_username()

user = subaccounts.User(REAL_USERNAME)

parser = OptionParser()

#                price=spot_price,
#                image_id=instance_info['image_id'],
#                count=instance_info['count'],
#                max_count=instance_info['count'],
#                key_name=instance_info['key_name'],
#                security_groups=instance_info['security_groups'],
#                user_data=instance_info['user_data'],
#                instance_type=instance_info['instance_type']
parser.add_option('-a','--ami',dest='image_id')
parser.add_option('-c','--count',default=1)
parser.add_option('-k','--key-name',default="%s-default" % (REAL_USERNAME))
parser.add_option('-z','--availability-zone')
parser.add_option('-g','--placement-group')
parser.add_option('-t','--instance-type')
parser.add_option('-u','--user-data')
parser.add_option('-s','--spot',dest='use_spot',action='store_true',default=False)
parser.add_option('--security-group',dest='security_groups',action='append',default=[])
parser.add_option('--stdin-user-data',action='store_true',default=False)
parser.add_option('--stdin-json',action='store_true',default=False)

(options, args) = parser.parse_args(sys.argv[1:])

if len(args) > 0:
    parser.error("too many arguments")

opt = vars(options)

request = {}
KEYS = [
    'image_id','count','key_name','availability_zone',
    'placement_group','instance_type','security_groups','user_data',
    'use_spot'
]

if opt['stdin_json']:
    sys.stderr.write("Loading request from stdin\n")
    request = simplejson.load(sys.stdin)
    if 'user_data' in request:
        request['user_data'] = base64.b64decode(request['user_data'])
else:
    for option_name in KEYS:
        if option_name in opt:
            request[option_name] = opt[option_name]

#sys.stderr.write("Starting instances based on request %s\n" % (request))

if 'key_name' not in request or not str(request['key_name']).startswith(REAL_USERNAME):
    parser.error("key_name required; must start with your username")

if 'placement' in request and  'availability_zone' not in request:
    request['availability_zone'] = request['placement']

if opt.get('stdin_user_data'):
    request['user_data'] = sys.stdin.read()

if len(user.get_access_keys()) == 0:
    raise Exception("No access keys for %s" % (REAL_USERNAME))

reservation_or_spot_requests = user.run_instances(request)

result = []
if request['use_spot']:
    result = [x.id for x in reservation_or_spot_requests]
else:
    result = [x.id for x in reservation_or_spot_requests.instances]

simplejson.dump(result, sys.stdout)
