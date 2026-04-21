#!/usr/bin/env python3
"""
CEEP Infrastructure — AWS CDK entry point.

Deploy order: StorageStack → ComputeStack → EtlStack → FrontendStack
Each stack exports resource ARNs so downstream stacks can import them.

Usage:
    cd infrastructure
    pip install -r requirements.txt
    cdk bootstrap        # first time only per account/region
    cdk deploy --all
"""

import aws_cdk as cdk

from stacks.storage_stack import StorageStack
from stacks.compute_stack import ComputeStack
from stacks.etl_stack import EtlStack
from stacks.frontend_stack import FrontendStack

app = cdk.App()

env = cdk.Environment(
    account="563142504525",
    region="us-east-1",
)

storage = StorageStack(app, "CeepStorageStack", env=env)

compute = ComputeStack(
    app,
    "CeepComputeStack",
    private_bucket=storage.private_bucket,
    public_bucket=storage.public_bucket,
    db_secret=storage.db_secret,
    db_endpoint=storage.db_endpoint,
    db_port=storage.db_port,
    vpc=storage.vpc,
    env=env,
)

etl = EtlStack(
    app,
    "CeepEtlStack",
    private_bucket=storage.private_bucket,
    public_bucket=storage.public_bucket,
    db_secret=storage.db_secret,
    db_endpoint=storage.db_endpoint,
    vpc=storage.vpc,
    env=env,
)

frontend = FrontendStack(
    app,
    "CeepFrontendStack",
    api_url=compute.api_url,
    env=env,
)

# Explicit dependency ordering
compute.add_dependency(storage)
etl.add_dependency(storage)
frontend.add_dependency(compute)

app.synth()
