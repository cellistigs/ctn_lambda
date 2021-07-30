import time
import os
from math import ceil
#from .env_vars import *

import boto3
import botocore

#from .config import IAM_ROLE, KEY_NAME, SECURITY_GROUPS, SHUTDOWN_BEHAVIOR

# Boto3 Resources & Clients
ec2_resource = boto3.resource('ec2')
ec2_client = boto3.client('ec2')
volume_available_waiter = ec2_client.get_waiter('volume_available')

def get_instance(instanceid,logger):
    """ Gets the instance given an instance id.  """
    instance = ec2_resource.Instance(instanceid)
    logger.append("        [Utils] Acquiring instance with id {}".format(instanceid))

    return instance

def start_instance_if_stopped(instance, logger):
    """ Check instance state, start if stopped & wait until ready """
    
    # Check & Report Status
    state = instance.state['Name']
    logger.append("        [Utils] Instance State: {}...".format(state))
    
    # If not running, run:
    if state != 'running':
        logger.append("        [Utils] Starting Instance...")
        instance.start()
        instance.wait_until_running()
        time.sleep(60)
        logger.append('Instance started!')
        

def start_instances_if_stopped(instances, logger):
    """ Check instance state, start if stopped & wait until ready """
    for instance in instances: 
        
        # Check & Report Status
        state = instance.state['Name']
        logger.append("        [Utils] Instance {} State: {}...".format(instance.id,state))
        
        # If not running, run:
        if state != 'running':
            try:
                logger.append("        [Utils] Starting Instance...")
                logger.write()
                instance.start()
                instance.wait_until_running()
                logger.append('        [Utils] Instance started!')
                logger.write()
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "UnsupportedOperation":
                    logger.append("        [Utils] Spot Instance, cannot be started manually. Waiting...")
                    logger.write()
                    ##TODO: figure out if you have to wait for this additionally. 
                    instance.wait_until_running()
                    logger.append('        [Utils] Instance started!')
                    logger.write()
                else:
                    print("unhandled error, quitting")
                    logger.append("        [Utils] unhandled error during job start, quitting")
                    logger.write()
                    raise Exception("[JOB TERMINATE REASON] Unhandled error communicating with AWS. Contact NeuroCAAS admin.")
        else:
            logger.append("        [Utils] Instance already running.")
            logger.write()
    logger.append("        [Utils] Initializing instances. This could take a moment...")
    logger.write()
    time.sleep(60)
    logger.append("        [Utils] All Instances Initialized.")
    logger.write()

def launch_new_instance(instance_type, ami, logger):
    """ Script To Launch New Instance From Image """
    logger.append("        [Utils] Acquiring new {} instance from {} ...".format(instance_type, ami))
    
    instances = ec2_resource.create_instances(
        ImageId=ami,
        InstanceType=instance_type,
        IamInstanceProfile={'Name': os.environ['IAM_ROLE']},
        MinCount=1,
        MaxCount=1,
        KeyName=os.environ['KEY_NAME'],
        SecurityGroups=[os.environ['SECURITY_GROUPS']],
        InstanceInitiatedShutdownBehavior=os.environ['SHUTDOWN_BEHAVIOR']
    )
    logger.append("        [Utils] New instance {} created!".format(instances[0]))
    return instances[0]

def launch_new_instance_with_tags(instance_type,ami,logger,timeout):
    """ Launch new instances with predetermined tags. 
    
    """
    assert type(timeout) == int
    tag_specifications = [
         {
        "ResourceType":"volume",
        "Tags":[
            {
                "Key":"PriceTracking",
                "Value":"On"
                },
            {
                "Key":"Timeout",    
                "Value":str(timeout)
                }
            ]
        },
        {
        "ResourceType":"instance",
        "Tags":[
            {
                "Key":"PriceTracking",
                "Value":"On"
                },
            {
                "Key":"Timeout",    
                "Value":str(timeout)
                }
            ]
        }]

    logger.append("        [Utils] Acquiring new {} instance from {} ...".format(instance_type, ami))
    print(tag_specifications)
    
    instances = ec2_resource.create_instances(
        ImageId=ami,
        IamInstanceProfile={'Name': os.environ['IAM_ROLE']},
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        KeyName=os.environ['KEY_NAME'],
        SecurityGroups=[os.environ['SECURITY_GROUPS']],
        TagSpecifications = tag_specifications,
        InstanceInitiatedShutdownBehavior=os.environ['SHUTDOWN_BEHAVIOR']
    )
    logger.append("        [Utils] New instance {} created!".format(instances[0]))
    return instances[0]


def launch_new_instances(instance_type, ami, logger, number, add_size, duration = None):
    """ Script To Launch New Instance From Image
    If duration parameter is specified, will launch the appropriate cost instance
    If number parameter is specified, will try to launch the requested number of instances. If not available, then will return none. 
    """
    logger.append("        [Utils] Acquiring new {} instances from {} ...".format(instance_type, ami))

    ## First parse the duration and figure out if there's anything we can do for it. 
    ## The duration should be given as the max number of minutes the job is expected to take. 
    if type(duration) == int:
        hours = ceil(duration/60)
        minutes_rounded = hours*60
        if minutes_rounded > 360:
            spot_duration = None
        else:
            spot_duration = minutes_rounded 
    elif duration is None:
        spot_duration = None
    else:
        logger.append("        [Utils] duration parameter is not valid. Must be an integer representing max number of minutes expected.")
        logger.write()
        raise ValueError("[JOB TERMINATE REASON] Given __duration__ parameter is not valid. Must be an integer, giving the maximum time expected in minutes.")

    ## Now parse the dataset size and figure if we should diverge from default behavior. 


    ## Now we will take the parsed duration and use it to launch instances.  
    
    if spot_duration is None:
        logger.append("        [Utils] save not available (duration not given or greater than 6 hours). Launching standard instance.")
        logger.write()
        response = ec2_client.describe_images(ImageIds = [os.environ["AMI"]])
        root = response["Images"][0]["RootDeviceName"]
        instances = ec2_resource.create_instances(
            BlockDeviceMappings=[
                {
                    "DeviceName": root,
                    "Ebs": {
                        "DeleteOnTermination": True,
                        "VolumeSize":add_size,
                        "VolumeType":"gp2",
                        "Encrypted": False
                        }
                    
                    }],
            ImageId=ami,
            InstanceType=instance_type,
            IamInstanceProfile={'Name': os.environ['IAM_ROLE']},
            MinCount=number,
            MaxCount=number,
            KeyName=os.environ['KEY_NAME'],
            SecurityGroups=[os.environ['SECURITY_GROUPS']],
            InstanceInitiatedShutdownBehavior=os.environ['SHUTDOWN_BEHAVIOR']
        )

    else:
        logger.append("        [Utils] Reserving save instance for {} minutes".format(spot_duration))
        marketoptions = {"MarketType":'spot',
                "SpotOptions":{
                    "SpotInstanceType":"one-time",
                    "BlockDurationMinutes":spot_duration,
                    }
                
                }
        try:
            instances = ec2_resource.create_instances(
                BlockDeviceMappings=[
                    {
                        "DeviceName": "/dev/sda1",
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "VolumeSize":add_size,
                            "VolumeType":"gp2",
                            "Encrypted": False
                            }
                        
                        }],
                ImageId=ami,
                InstanceType=instance_type,
                IamInstanceProfile={'Name': os.environ['IAM_ROLE']},
                MinCount=number,
                MaxCount=number,
                KeyName=os.environ['KEY_NAME'],
                SecurityGroups=[os.environ['SECURITY_GROUPS']],
                InstanceInitiatedShutdownBehavior=os.environ['SHUTDOWN_BEHAVIOR'],
                InstanceMarketOptions = marketoptions
            )
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "InsufficientInstanceCapacity":
                logger.append("        [Utils] Save not available (beyond available aws capacity). Launching standard instance.")
                logger.write()
                instances = ec2_resource.create_instances(
                    BlockDeviceMappings=[
                        {
                            "DeviceName": "/dev/sda1",
                            "Ebs": {
                                "DeleteOnTermination": True,
                                "VolumeSize":add_size,
                                "VolumeType":"gp2",
                                "Encrypted": False
                                }
                            
                            }],
                    ImageId=ami,
                    InstanceType=instance_type,
                    IamInstanceProfile={'Name': os.environ['IAM_ROLE']},
                    MinCount=number,
                    MaxCount=number,
                    KeyName=os.environ['KEY_NAME'],
                    SecurityGroups=[os.environ['SECURITY_GROUPS']],
                    InstanceInitiatedShutdownBehavior=os.environ['SHUTDOWN_BEHAVIOR']
                )
            else:
                logger.append("        [Utils] unhandled error while launching save instances. contact NeuroCAAS admin.")
                raise ValueError("[JOB TERMINATE REASON] Unhandled exception")

    [logger.append("        [Utils] New instance {} created!".format(instances[i])) for i in range(number)]
    logger.write()
    return instances

def launch_new_instances_with_tags(instance_type, ami, logger, number, add_size, duration = None):
    """ Script To Launch New Instance From Image
    If duration parameter is specified, will launch the appropriate cost instance
    If number parameter is specified, will try to launch the requested number of instances. If not available, then will return none. 
    """
    logger.append("        [Utils] Acquiring new {} instances from {} ...".format(instance_type, ami))

    ## First parse the duration and figure out if there's anything we can do for it. 
    ## The duration should be given as the max number of minutes the job is expected to take. 
    if type(duration) == int:
        hours = ceil(duration/60)
        minutes_rounded = hours*60
        if minutes_rounded > 360:
            spot_duration = None
        else:
            spot_duration = minutes_rounded 
    elif duration is None:
        spot_duration = None
    else:
        logger.append("        [Utils] duration parameter is not valid. Must be an integer representing max number of minutes expected.")
        logger.write()
        raise ValueError("[JOB TERMINATE REASON] Given __duration__ parameter is not valid. Must be an integer, giving the maximum time expected in minutes.")

    ## Now parse the dataset size and figure if we should diverge from default behavior. 


    ## Now we will take the parsed duration and use it to launch instances.  
    response = ec2_client.describe_images(ImageIds = [os.environ["AMI"]])
    root = response["Images"][0]["RootDeviceName"]
    bdm = [
            {
                "DeviceName": root,
                "Ebs": {
                    "DeleteOnTermination": True,
                    "VolumeSize":add_size,
                    "VolumeType":"gp2",
                    "Encrypted": False
                    }
                
                }
            ]

    assert type(duration) == int
    tag_specifications = [
         {
        "ResourceType":"volume",
        "Tags":[
            {
                "Key":"PriceTracking",
                "Value":"On"
                },
            {
                "Key":"Timeout",    
                "Value":str(duration)
                }
            ]
        },
        {
        "ResourceType":"instance",
        "Tags":[
            {
                "Key":"PriceTracking",
                "Value":"On"
                },
            {
                "Key":"Timeout",    
                "Value":str(duration)
                }
            ]
        }]
    
    if spot_duration is None:
        logger.append("        [Utils] save not available (duration not given or greater than 6 hours). Launching standard instance.")
        logger.write()
        response = ec2_client.describe_images(ImageIds = [os.environ["AMI"]])
        root = response["Images"][0]["RootDeviceName"]
        instances = ec2_resource.create_instances(
            BlockDeviceMappings= bdm,
            ImageId=ami,
            InstanceType=instance_type,
            IamInstanceProfile={'Name': os.environ['IAM_ROLE']},
            MinCount=number,
            MaxCount=number,
            TagSpecifications = tag_specifications,
            KeyName=os.environ['KEY_NAME'],
            SecurityGroups=[os.environ['SECURITY_GROUPS']],
            InstanceInitiatedShutdownBehavior=os.environ['SHUTDOWN_BEHAVIOR']
        )

    else:
        logger.append("        [Utils] Reserving save instance for {} minutes".format(spot_duration))
        marketoptions = {"MarketType":'spot',
                "SpotOptions":{
                    "SpotInstanceType":"one-time",
                    "BlockDurationMinutes":spot_duration,
                    }
                
                }
        try:
            instances = ec2_resource.create_instances(
                BlockDeviceMappings= bdm,
                ImageId=ami,
                InstanceType=instance_type,
                IamInstanceProfile={'Name': os.environ['IAM_ROLE']},
                MinCount=number,
                MaxCount=number,
                TagSpecifications = tag_specifications,
                KeyName=os.environ['KEY_NAME'],
                SecurityGroups=[os.environ['SECURITY_GROUPS']],
                InstanceInitiatedShutdownBehavior=os.environ['SHUTDOWN_BEHAVIOR'],
                InstanceMarketOptions = marketoptions
            )
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "InsufficientInstanceCapacity":
                logger.append("        [Utils] Save not available (beyond available aws capacity). Launching standard instance.")
                logger.write()
                instances = ec2_resource.create_instances(
                    BlockDeviceMappings=bdm,
                    ImageId=ami,
                    InstanceType=instance_type,
                    IamInstanceProfile={'Name': os.environ['IAM_ROLE']},
                    MinCount=number,
                    MaxCount=number,
                    TagSpecifications = tag_specifications,
                    KeyName=os.environ['KEY_NAME'],
                    SecurityGroups=[os.environ['SECURITY_GROUPS']],
                    InstanceInitiatedShutdownBehavior=os.environ['SHUTDOWN_BEHAVIOR']
                )
            else:
                print(e.response)
                logger.append("        [Utils] unhandled error while launching save instances. contact NeuroCAAS admin.")
                raise ValueError("[JOB TERMINATE REASON] Unhandled exception")

    [logger.append("        [Utils] New instance {} created!".format(instances[i])) for i in range(number)]
    logger.write()
    return instances

def count_active_instances(instance_type):
    """
    Counts how many active [including transition in and out] isntances there are of a certain type. 
    Inputs:
    instance_type (str): string specifying instance type
    Outputs: 
    (int): integer giving number of instances currently active. 
    """
    instances = ec2_resource.instances.filter(Filters=[{'Name': 'instance-state-name', 'Values': ['running','pending','stopping','shutting-down']},{'Name':'instance-type',"Values":[instance_type]}])
    return len([i for i in instances])

def prepare_volumes(instances_info):
    """
    For each instance id that you pass to this function, the function will create and attach volumes to the instance to accomodate data sizes.  
    Inputs: 
    instances_info (dict): a dictionary with instance ids as keys and required dataset sizes as values (integers).  
    Outputs:
    (dict): a dictionary where the instance ids as keys and the create and attach response codes. 
    """
    all_responses = {}
    if instances_info is None:
        pass
    else:
        for instance_id in instances_info:
            template_response = {"create":None,"attach":None,"mod":None}
            size = instances_info[instance_id]
            ## Get the availability zone from describing the instances. 
            avzone = ec2_client.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["Placement"]["AvailabilityZone"]
            ## Create the volume.
            createoutput = ec2_client.create_volume(AvailabilityZone = avzone,Size = size,VolumeType = "gp2")
            volume_available_waiter.wait(VolumeIds=[createoutput["VolumeId"]])
            ## Attach that to the instance: (Were assuming it's initialized and ready)
            attachoutput = ec2_client.attach_volume(Device = "/dev/sdh",InstanceId=instance_id,VolumeId = createoutput["VolumeId"])
            ## Finally, alter the termination status so the volume terminates with the instance. 
            modoutput = ec2_client.modify_instance_attribute(BlockDeviceMappings = [{"DeviceName":"/dev/sdh","Ebs":{"DeleteOnTermination":True,"VolumeId":createoutput["VolumeId"]}}],InstanceId = instance_id)
            template_response["create"] = createoutput
            template_response["attach"] = attachoutput
            template_response["mod"] = modoutput
            all_responses[instance_id] = template_response
    return all_responses

def get_volumesize(imageid):
    """
    Given the id of an ami, returns the volume size associated with the root device. 
    Inputs: 
    imageid (str): a string giving the id of the ami we will be analyzing. 
    Outputs: 
    (int): an integer giving the size of the volume assigned to the AMI. 
    """
    response = ec2_client.describe_images(ImageIds = [imageid])
    root = response["Images"][0]["RootDeviceName"]
    mappings = response["Images"][0]["BlockDeviceMappings"]
    rootdevice = [m for m in mappings if m["DeviceName"] == root][0]
    rootdevicevolume = rootdevice["Ebs"]["VolumeSize"]
    return(rootdevicevolume)



