from environmentbase.template import Template
from environmentbase import resources
from troposphere import Ref, Base64, Join, Output, GetAtt, ec2

SCHEME_INTERNET_FACING = 'internet-facing'
SCHEME_INTERNAL = 'internal'
PUBLIC_ACCESS_CIDR = '0.0.0.0/0'


class HaCluster(Template):
    """
    Generic highly available cluster template
    Contains an ELB, Autoscaling Group, Security Groups, and optional internal DNS record
    """

    def __init__(self, 
                 name='HaCluster', 
                 ami_name='amazonLinuxAmiId', 
                 elb_ports={80: 80}, 
                 user_data='', 
                 env_vars={},
                 min_size=1, max_size=1,
                 instance_type='t2.micro',
                 subnet_layer='private',
                 elb_scheme=SCHEME_INTERNET_FACING,
                 elb_health_check_port=None):

        # This will be the name used in resource names and descriptions
        self.name = name

        # This is the name used to identify the AMI from the ami_cache.json file
        self.ami_name = ami_name

        # This should be a dictionary mapping ELB ports to Instance ports
        self.elb_ports = elb_ports

        # This is the contents of the userdata script as a string
        self.user_data = user_data

        # This is a dictionary of environment variables to inject into the instances
        self.env_vars = env_vars

        # These define the lower and upper boundaries of the autoscaling group
        self.min_size = min_size
        self.max_size = max_size

        # The type of instance for the autoscaling group
        self.instance_type = instance_type
        
        # This is the subnet layer that the ASG is in (public, private, ...)
        self.subnet_layer = subnet_layer

        # This is the type of ELB: internet-facing gets a publicly accessible DNS, while internal is only accessible to the VPC
        self.elb_scheme = elb_scheme

        # This is the health check port for the cluster
        # TODO: Implement this functionality in template.add_elb and pass this value through
        self.elb_health_check_port = elb_health_check_port

        # This is an optional DNS entry to create a CNAME in a private hosted zone
        # TODO: Use template.register_elb_to_dns()

        super(HaCluster, self).__init__(template_name=self.name)


    def build_hook(self):
        """
        Hook to add tier-specific assets within the build stage of initializing this class.
        """

        # Create security groups for the ASG and ELB and connect them together
        self.add_security_groups()

        # Add the IAM role for the autoscaling group
        self.add_cluster_instance_profile()

        # Add the ELB for the autoscaling group
        self.add_cluster_elb()

        # Add the userdata for the autoscaling group
        self.add_user_data()

        # Add the autoscaling group for the cluster
        self.add_cluster_asg()

        # Add the outputs for the stack
        self.add_outputs()


    def add_security_groups(self):
        """
        Wrapper method to encapsulate process of creating security groups for this tier
        Creates security groups for both ASG and ELB and opens the ports between them
        Sets self.security_groups as a dictionary with two security_groups: ha_cluster and elb
        """
        # Determine ingress rules for ELB security -- open to internet for internet-facing ELB, open to VPC for internal ELB
        access_cidr = PUBLIC_ACCESS_CIDR if self.elb_scheme == SCHEME_INTERNET_FACING else self.vpc_cidr

        # Create the ingress rules to the ELB security group
        elb_sg_ingress_rules = []
        for elb_port in self.elb_ports:
            elb_sg_ingress_rules.append(ec2.SecurityGroupRule(FromPort=elb_port, ToPort=elb_port, IpProtocol='tcp', CidrIp=access_cidr))

        # Create the ELB security group and attach the ingress rules
        elb_sg_name = '%sElbSecurityGroup' % self.name
        elb_sg = self.add_resource(
            ec2.SecurityGroup(
                elb_sg_name,
                GroupDescription='Security group for %s ELB' % self.name,
                VpcId=self.vpc_id,
                SecurityGroupIngress=elb_sg_ingress_rules)
        )

        # Create the ASG security group 
        ha_cluster_sg_name = '%sSecurityGroup' % self.name
        ha_cluster_sg = self.add_resource(
            ec2.SecurityGroup(
                ha_cluster_sg_name,
                GroupDescription='Security group for %s' % self.name,
                VpcId=self.vpc_id)
        )

        # Create the reciprocal rules between the ELB and the ASG
        for instance_port in self.elb_ports.values():
            self.create_reciprocal_sg(
                elb_sg, elb_sg_name,
                ha_cluster_sg, ha_cluster_sg_name,
                from_port=instance_port)

        self.security_groups = {'ha_cluster': ha_cluster_sg, 'elb': elb_sg}

        return self.security_groups


    def add_cluster_instance_profile(self):
        """
        Wrapper method to encapsulate process of adding the IAM role for the autoscaling group
        Sets self.instance_profile with the IAM Role resource, used in creation of the Launch Configuration
        """
        self.instance_profile = None


    def add_cluster_elb(self):
        """
        Wrapper method to encapsulate process of creating the ELB for the autoscaling group
        Sets self.cluster_elb with the ELB resource
        """
        # Determine the subnet layer of the ELB based on the scheme -- public if it's internet facing, else use the same subnet layer as the ASG
        elb_subnet_layer = 'public' if self.elb_scheme == SCHEME_INTERNET_FACING else self.subnet_layer

        # This creates the ELB, opens the specified ports, and attaches the security group and logging bucket
        self.cluster_elb = self.add_elb(
            resource_name=self.name,
            security_groups=[self.security_groups['elb']],
            ports=self.elb_ports,
            utility_bucket=self.utility_bucket,
            subnet_layer=elb_subnet_layer,
            scheme=self.elb_scheme
        )


    def add_user_data(self):
        """
        Wrapper method to encapsulate process of constructing userdata for the autoscaling group
        Sets self.user_data_payload constructed from the passed in user_data and env_vars 
        """
        self.user_data_payload = {}
        if self.user_data:
            self.user_data_payload = self.build_bootstrap(
                bootstrap_files=[self.user_data],
                variable_declarations=["%s=%s" % (k, v) for k,v in self.env_vars.iteritems()])


    def add_cluster_asg(self):
        """
        Wrapper method to encapsulate process of creating the autoscaling group
        Sets self.cluster_asg with the autoscaling group resource
        """
        self.cluster_asg = self.add_asg(
            layer_name=self.name,
            security_groups=[self.security_groups['ha_cluster'], self.common_security_group],
            load_balancer=self.cluster_elb,
            ami_name=self.ami_name,
            user_data=self.user_data_payload,
            instance_type=self.instance_type,
            min_size=self.min_size,
            max_size=self.max_size,
            subnet_type=self.subnet_layer,
            instance_profile=self.instance_profile
        )

    def add_outputs(self):
        """
        Wrapper method to encapsulate creation of stack outputs for this template
        """
        self.add_output(Output('%sELBDNSName' % self.name, Value=GetAtt(self.cluster_elb, 'DNSName')))
        self.add_output(Output('%sSecurityGroupId' % self.name, Value=Ref(self.security_groups['ha_cluster'])))
        self.add_output(Output('%sElbSecurityGroupId' % self.name, Value=Ref(self.security_groups['elb'])))

