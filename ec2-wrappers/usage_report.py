#!/usr/bin/python

import record_usage
import audit
from sys import argv

username = audit.real_username()
if ((audit.real_username() == 'cs61c' or
     audit.real_username().startswith('cs61c-t') or
     audit.real_username() == 'charles') and
    len(argv) > 1):
    username = argv[1]

if username != 'ALL':
    (desc, total) = record_usage.user_report(username)
    print "Usage report for %s:\n%s" % (username, desc)
    print "estimated total spending = $%6.3f" % (total)
else:
    overall_total = 0.0
    for user in record_usage.users():
        (desc, total) = record_usage.user_report(user, include_live=False)
        print "%-20s $%6.3f" % (user, total)
        overall_total += total
    print "(sum = $%6.3f)" % (overall_total)
