from troposphere import Template, Select, Ref, Parameter, FindInMap, Output, Base64, Join, GetAtt
import troposphere.iam as iam
import troposphere.ec2 as ec2
import troposphere.s3 as s3
import hashlib
import json
from datetime import datetime
from environmentbase import EnvironmentBase
from docopt import docopt

class TemplateBase(EnvironmentBase):

    def __init__(self, arg_dict):
        EnvironmentBase.__init__(self, arg_dict)

        self.vpc_cidr = self.template.add_parameter(Parameter('vpcCidr', 
            Description='CIDR of the VPC network', 
            Type='String', 
            AllowedPattern=self.strings['cidr_regex'], 
            ConstraintDescription=self.strings['cidr_regex_message']))

        self.vpc_id = self.template.add_parameter(Parameter('vpcId',
            Description='ID of the VPC network', 
            Type='String'))

        self.common_security_group = self.template.add_parameter(Parameter('commonSecurityGroup', 
            Description='Security Group ID of the common security group for this environment', 
            Type='String'))

        self.utility_bucket = self.template.add_parameter(Parameter('utilityBucket', 
            Description='Name of the S3 bucket used for infrastructure utility', 
            Type='String'))

        network_config = arg_dict.get('network', {})
        for y in ['public', 'private']:
            if y not in self.subnets:
                self.subnets[y] = []
            for x in range(0, max(int(network_config.get('public_subnet_count', 2)), int(network_config.get('private_subnet_count', 2)))):
                self.subnets[y].append(Ref(self.template.add_parameter(Parameter(y.lower() + 'Subnet' + str(x), 
                    Description='Private subnet ' + str(x), 
                    Type='String'))))