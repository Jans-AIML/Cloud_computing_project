"""
StorageStack — Tier 3: S3 buckets, RDS PostgreSQL, KMS keys, VPC.

Resources created:
- KMS CMK (for S3 private bucket + RDS encryption)
- S3 private bucket  (raw community emails — SSE-KMS, BlockPublicAccess)
- S3 public-docs bucket (parsed JSON, public document text — SSE-S3)
- S3 frontend bucket (static React build — public read via CloudFront OAI only)
- VPC (2 AZs, private subnets for DB + Lambda)
- RDS PostgreSQL 15 db.t3.micro with pgvector extension
- Secrets Manager secret for DB credentials
"""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_s3 as s3,
    aws_kms as kms,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
)
from constructs import Construct


class StorageStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── KMS Customer Managed Key ──────────────────────────────────────────
        self.cmk = kms.Key(
            self,
            "CeepCmk",
            alias="alias/ceep-cmk",
            description="CEEP master key — encrypts private S3 bucket and RDS",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,  # never auto-delete encryption keys
        )

        # ── VPC ───────────────────────────────────────────────────────────────
        # Two private subnets (Lambda + RDS) and two public subnets.
        # NAT instance (t3.nano ~$3/mo) instead of NAT Gateway (~$32/mo).
        self.vpc = ec2.Vpc(
            self,
            "CeepVpc",
            max_azs=2,
            nat_gateways=0,  # we add a NAT instance below to save cost
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # Cheap NAT instance (t3.nano ≈ $3/mo) instead of managed NAT GW (~$32/mo)
        nat_instance = ec2.NatProvider.instance_v2(
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.NANO),
        )
        self.vpc = ec2.Vpc(
            self,
            "CeepVpcWithNat",
            max_azs=2,
            nat_gateways=1,
            nat_gateway_provider=nat_instance,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # VPC endpoints so Lambda/Glue can reach AWS services without NAT
        self.vpc.add_gateway_endpoint(
            "S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3
        )
        self.vpc.add_interface_endpoint(
            "ComprehendEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.COMPREHEND,
        )
        self.vpc.add_interface_endpoint(
            "BedrockEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
        )
        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
        )

        # ── S3: Private bucket (raw community emails) ─────────────────────────
        self.private_bucket = s3.Bucket(
            self,
            "CeepPrivateBucket",
            bucket_name=f"ceep-private-uploads-{self.account}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.cmk,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                # Non-current versions purged after 90 days (GDPR-friendly)
                s3.LifecycleRule(
                    noncurrent_version_expiration=Duration.days(90),
                )
            ],
        )

        # ── S3: Public-docs bucket (parsed JSON, public source text) ──────────
        self.public_bucket = s3.Bucket(
            self,
            "CeepPublicDocsBucket",
            bucket_name=f"ceep-public-docs-{self.account}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,  # CloudFront OAI only
            versioned=False,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── S3: Frontend bucket (static React build — served by CloudFront) ───
        self.frontend_bucket = s3.Bucket(
            self,
            "CeepFrontendBucket",
            bucket_name=f"ceep-frontend-{self.account}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            website_index_document="index.html",
            website_error_document="index.html",  # SPA fallback
        )

        # ── RDS Secrets (DB credentials) ──────────────────────────────────────
        self.db_secret = secretsmanager.Secret(
            self,
            "CeepDbSecret",
            secret_name="ceep/db/credentials",
            description="CEEP RDS PostgreSQL master credentials",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "ceep_admin"}',
                generate_string_key="password",
                exclude_characters=" %+~`#$&*()|[]{}:;<>?!'/@\"\\,=^",
                password_length=32,
            ),
        )

        # ── RDS Security Group ────────────────────────────────────────────────
        self.rds_sg = ec2.SecurityGroup(
            self, "CeepRdsSg", vpc=self.vpc, description="CEEP RDS SG"
        )

        # ── RDS PostgreSQL 15 (db.t3.micro — free tier) ───────────────────────
        self.db_instance = rds.DatabaseInstance(
            self,
            "CeepPostgres",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_15
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
            ),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[self.rds_sg],
            credentials=rds.Credentials.from_secret(self.db_secret),
            database_name="ceep",
            storage_encrypted=True,
            storage_encryption_key=self.cmk,
            allocated_storage=20,
            backup_retention=Duration.days(7),
            deletion_protection=False,  # set True for production
            removal_policy=RemovalPolicy.SNAPSHOT,
            enable_performance_insights=False,  # costs extra; enable in prod
            # Parameter group: enable pgvector extension
            parameters={
                "shared_preload_libraries": "pg_stat_statements",
            },
        )

        # Convenience properties consumed by other stacks
        self.db_endpoint = self.db_instance.db_instance_endpoint_address
        self.db_port = self.db_instance.db_instance_endpoint_port

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(self, "PrivateBucketName", value=self.private_bucket.bucket_name)
        CfnOutput(self, "PublicBucketName", value=self.public_bucket.bucket_name)
        CfnOutput(self, "FrontendBucketName", value=self.frontend_bucket.bucket_name)
        CfnOutput(self, "DbEndpoint", value=self.db_endpoint)
        CfnOutput(self, "DbSecretArn", value=self.db_secret.secret_arn)
        CfnOutput(self, "CmkArn", value=self.cmk.key_arn)
