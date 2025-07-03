#!/usr/bin/env python3

import pulumi
import pulumi_aws as aws
from strongmind_deployment.container import ContainerComponent

# Configure AWS provider for us-east-1
aws_provider = aws.Provider("aws-east", region="us-east-1")

# Get the current stack name for resource naming
stack = pulumi.get_stack()
project = pulumi.get_project()

# ECR image configuration (updated for us-east-1)
ecr_image = os.getenv("CONTAINER_IMAGE")

# Create the container component for ECS deployment
container = ContainerComponent(
    "container",
    container_image=ecr_image,
    container_port=8000,  # Adjust based on your app's port
    # Configure resource requirements
    cpu=512,  # 0.5 vCPU (in CPU units)
    memory=1024,  # 1 GB (in MB)
    # Environment variables
    env_vars={
        "ENVIRONMENT": stack,
        "REGION": "us-east-1"
    },
    # Scaling configuration
    desired_count=2,  # Number of tasks to run
    autoscale_threshold=5,  # Response time threshold for autoscaling
    # Load balancer configuration
    need_load_balancer=True,
    # Namespace for resource naming
    namespace=f"{project}-{stack}",
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# Export useful outputs
pulumi.export("container_image", ecr_image)
pulumi.export("region", "us-east-1")
pulumi.export("namespace", f"{project}-{stack}")
pulumi.export("ecs_cluster_arn", container.ecs_cluster_arn)
if container.load_balancer:
    pulumi.export("load_balancer_dns", container.load_balancer.dns_name)
if container.target_group:
    pulumi.export("target_group_arn", container.target_group.arn) 