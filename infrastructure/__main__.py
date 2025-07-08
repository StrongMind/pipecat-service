#!/usr/bin/env python3

import os
import pulumi
import pulumi_aws as aws
from strongmind_deployment.container import ContainerComponent
from strongmind_deployment.secrets import SecretsComponent

# Get the current stack name for resource naming
stack = pulumi.get_stack()
project = pulumi.get_project()
region = aws.get_region().name

# ECR image configuration (updated for us-east-1)
ecr_image = os.getenv("CONTAINER_IMAGE")

secrets = SecretsComponent(
    "secrets"
)

# Create the container component for ECS deployment
container = ContainerComponent(
    "container",
    secrets=secrets.get_secrets(),
    container_image=ecr_image,
    container_port=8080,  # Adjust based on your app's port
    # Environment variables
    env_vars={
        "ENVIRONMENT": stack,
        "REGION": region
    },
    # Scaling configuration
    desired_count=2,  # Number of tasks to run
    autoscale_threshold=5,  # Response time threshold for autoscaling
    # Load balancer configuration
    need_load_balancer=True,
    # Namespace for resource naming
    namespace=f"{project}-{stack}",
)

# Export useful outputs
pulumi.export("container_image", ecr_image)
pulumi.export("region", region)
pulumi.export("namespace", f"{project}-{stack}")
pulumi.export("ecs_cluster_arn", container.ecs_cluster_arn)
if container.load_balancer:
    pulumi.export("load_balancer_dns", container.load_balancer.dns_name)
if container.target_group:
    pulumi.export("target_group_arn", container.target_group.arn) 