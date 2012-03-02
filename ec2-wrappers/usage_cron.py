#!/usr/bin/python
import record_usage

record_usage.init_db()
record_usage.update_instances()
record_usage.update_spot_requests()
