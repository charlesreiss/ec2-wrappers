import hadoop.cloud.providers.ec2
import simplejson
import subprocess
import base64
import os
import pwd
import re

from boto.ec2.connection import EC2Connection

EC2_RUNNER = '/home/ff/cs61c/bin/ec2-run'

class CS61CEc2Cluster(hadoop.cloud.providers.ec2.Ec2Cluster):
    """
    EC2 wrapper to use privallege hole for running instances;
    everything else is done directly with the IAM credentials.
    """

    @staticmethod
    def get_clusters_with_role(role, state="running"):
        username = os.environ.get('FAKE_USERNAME')
        if username is None:
            username = pwd.getpwuid(os.getuid()).pw_name
        all_instances = EC2Connection().get_all_instances()
        clusters = []
        for res in all_instances:
          instance = res.instances[0]
          if instance.key_name.startswith(username):
            for group in res.groups:
              if group.id.endswith("-" + role) and instance.state == state:
                clusters.append(re.sub("-%s$" % re.escape(role), "", group.id))
        return clusters

    def __init__(self, name, config_dir):
        super(CS61CEc2Cluster, self).__init__(name, config_dir)
    
    def get_provider_code(self):
        return "cs61cec2"

    def launch_instances(self, roles, number, image_id, size_id,
                         instance_user_data, **kwargs):
        for role in roles:
            self._check_role_name(role)
            self._create_groups(role)

        user_data = instance_user_data.read_as_gzip_stream()
        security_groups = self._get_group_names(roles) + kwargs.get('security_groups', [])

        use_spot = kwargs.get('use_spot', False)
        
        request = {
            'image_id': image_id,
            'count': number,
            'key_name': kwargs.get('key_name', None),
            'security_groups': security_groups,
            'instance_type': size_id,
            'placement': kwargs.get('placement', None),
            'placement_group': kwargs.get('placement_group', None),
            'use_spot': use_spot,
            'user_data': base64.b64encode(user_data)
        }

        proc = subprocess.Popen(
            [EC2_RUNNER, '--stdin-json'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        # print "Making raw request %s" % (request)
        simplejson.dump(request, proc.stdin)
        proc.stdin.close()
        result = simplejson.load(proc.stdout)
        proc.wait()

        if use_spot:
            spot_instance_request_ids = [request in result]
            instance_ids = wait_for_spot_instances(spot_instance_request_ids)
            return instance_ids
        else:
            return [instance for instance in result]

#http://tech.backtype.com/patching-the-cloudera-ec2-boot-scripts-for-sp
    def wait_for_spot_instances(self, request_ids, timeout=1200):
        start_time = time.time()
        while True:
          if (time.time() - start_time >= timeout):
            raise TimeoutException()
          try:
            instance_ids = [request.instanceId for request in self.ec2Connection.get_all_spot_instance_requests(request_ids)]
            if self._all_started(self.ec2Connection.get_all_instances(instance_ids)):
              return instance_ids
          except AttributeError:
            pass
          # don't timeout for race condition where instance is not yet registered
          except EC2ResponseError:
            pass
          time.sleep(15)

    def _get_spot_requests(self, cluster):
        requests = self.ec2Connection.get_all_spot_instance_requests()
        requests = filter(lambda x:cluster in x.launch_specification.groups, requests)
        return requests

    def terminate(self):
        for request in self._get_spot_requests(self._get_cluster_group_name()):
            request.cancel()
        instances = self._get_instances(self._get_cluster_group_name(), 'running')
        if instances:
            self.ec2Connection.terminate_instances([i.id for i in instances])


