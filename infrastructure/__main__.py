#!/usr/bin/env python3

import os
import pulumi
import pulumi_aws as aws
from strongmind_deployment.container import ContainerComponent
from strongmind_deployment.secrets import SecretsComponent

stack = pulumi.get_stack()
project = pulumi.get_project()
region = aws.get_region().name

ecr_image = os.getenv("CONTAINER_IMAGE")

secrets = SecretsComponent("secrets")

container = ContainerComponent(
    "container",
    secrets=secrets.get_secrets(),
    container_image=ecr_image,
    container_port=8080,
    env_vars={"ENVIRONMENT": stack, "REGION": region},
    desired_count=2,  # Number of tasks to run
    autoscale_threshold=5,  # Response time threshold for autoscaling
    need_load_balancer=True,
)
