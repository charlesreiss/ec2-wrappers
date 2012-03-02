from boto.ec2.connection import EC2Connection
from boto.iam import IAMConnection
import simplejson

from cs61cpaths import ROOT_ACCESS_KEY_FILE

root_creds = None
def get_root_creds():
    global root_creds
    if root_creds is None:
        fh = open(ROOT_ACCESS_KEY_FILE, 'r')
        root_creds = simplejson.load(fh)
        fh.close()
    return root_creds

    
def get_root_ec2_connection():
    creds = get_root_creds()
    return EC2Connection(
        aws_access_key_id = str(creds['aws_access_key_id']),
        aws_secret_access_key = str(creds['aws_secret_access_key']),
        debug = 0
    )

def get_root_IAM_connection():
    creds = get_root_creds()
    return IAMConnection(
        aws_access_key_id = str(creds['aws_access_key_id']),
        aws_secret_access_key = str(creds['aws_secret_access_key']),
        debug = 0
    )

