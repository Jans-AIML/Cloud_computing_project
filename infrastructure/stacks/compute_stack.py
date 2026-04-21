"""
ComputeStack — Tier 2: Lambda (FastAPI/Mangum) + API Gateway.

API Gateway is the SOLE entry point for all client requests.
Every route (/documents, /search, /rag, /briefs) goes through API GW → Lambda.

Resources created:
- Lambda security group (allows egress to RDS)
- Lambda function (FastAPI app via Mangum, Docker container image)
- API Gateway HTTP API with CORS
- IAM role with least-privilege policies:
    S3 read/write, Secrets Manager read (DB + Groq), SQS SendMessage
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
)
from constructs import Construct


class ComputeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        private_bucket: s3.IBucket,
        public_bucket: s3.IBucket,
        db_secret: secretsmanager.ISecret,
        db_endpoint: str,
        db_port: str,
        vpc: ec2.IVpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Lambda Security Group ─────────────────────────────────────────────
        lambda_sg = ec2.SecurityGroup(
            self,
            "CeepLambdaSg",
            vpc=vpc,
            description="CEEP Lambda SG - egress to RDS and VPC endpoints",
            allow_all_outbound=True,  # VPC endpoints handle traffic internally
        )

        # NOTE: RDS SG ingress rule (Lambda → RDS port 5432) was added via CLI:
        # aws ec2 authorize-security-group-ingress --group-id <rds-sg-id>
        #   --protocol tcp --port 5432 --source-group <lambda-sg-id>
        # Cross-stack SG references create cyclic dependencies in CDK.

        # ── Lambda Execution Role ─────────────────────────────────────────────
        lambda_role = iam.Role(
            self,
            "CeepLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # S3: read from public-docs, write parsed JSON, read private for pre-signed URL generation
        public_bucket.grant_read_write(lambda_role)
        # private bucket: put (presigned upload), get (download for /process ETL), delete (right-to-erasure)
        private_bucket.grant_read_write(lambda_role)
        private_bucket.grant_delete(lambda_role)

        # Secrets Manager: read DB credentials
        db_secret.grant_read(lambda_role)

        # Groq API key secret
        groq_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "GroqApiKeySecret", "ceep/groq/api-key"
        )
        groq_secret.grant_read(lambda_role)

        # SQS: send ETL jobs to the queue (ETL stack creates the queue; ARN passed via env)
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="SqsSendMessage",
                actions=["sqs:SendMessage", "sqs:GetQueueUrl"],
                resources=["*"],  # narrowed after ETL stack creates the queue
            )
        )

        # X-Ray tracing
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="XRay",
                actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
                resources=["*"],
            )
        )

        # ── Lambda Function ───────────────────────────────────────────────────
        self.api_lambda = _lambda.DockerImageFunction(
            self,
            "CeepApiLambda",
            code=_lambda.DockerImageCode.from_image_asset(
                "../backend",
                platform=ecr_assets.Platform.LINUX_AMD64,
            ),
            role=lambda_role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[lambda_sg],
            timeout=Duration.seconds(120),
            memory_size=1024,
            tracing=_lambda.Tracing.ACTIVE,
            environment={
                "DB_HOST": db_endpoint,
                "DB_PORT": db_port,
                "DB_NAME": "ceep",
                "DB_SECRET_ARN": db_secret.secret_arn,
                "PUBLIC_BUCKET": public_bucket.bucket_name,
                "PRIVATE_BUCKET": private_bucket.bucket_name,
                "AWS_REGION_NAME": self.region,
                "GROQ_SECRET_ARN": groq_secret.secret_arn,
                "GROQ_CHAT_MODEL": "llama-3.1-8b-instant",
                "LLM_PROVIDER": "groq",
                "USE_LOCAL_STORAGE": "false",
                "LOCAL_STORAGE_PATH": "/tmp/ceep_data",
                "EMBED_DIM": "384",
                "ENVIRONMENT": "production",
            },
        )

        # ── API Gateway HTTP API ──────────────────────────────────────────────
        # API Gateway is the SOLE entry point; every client request goes through it.
        lambda_integration = integrations.HttpLambdaIntegration(
            "CeepLambdaIntegration", self.api_lambda
        )

        self.http_api = apigwv2.HttpApi(
            self,
            "CeepHttpApi",
            api_name="ceep-api",
            description="CEEP API Gateway — sole entry point for all client requests",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.PUT,
                    apigwv2.CorsHttpMethod.DELETE,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["Content-Type", "Authorization", "X-Request-Id"],
                max_age=Duration.hours(1),
            ),
        )

        # Routes — all traffic through API Gateway
        route_configs = [
            ("POST",   "/documents/upload",        "Upload document (returns pre-signed S3 URL)"),
            ("POST",   "/documents/{id}/process", "Run ETL in-process after S3 PUT (PDF/email)"),
            ("GET",    "/documents",              "List evidence cards"),
            ("GET",    "/documents/{id}",         "Get single evidence card"),
            ("DELETE", "/documents/{id}",         "Delete document + embeddings"),
            ("GET",    "/search",                 "Keyword + vector search"),
            ("POST",   "/rag/query",              "RAG Q&A with citations"),
            ("POST",   "/rag/stream",             "Streaming RAG Q&A"),
            ("POST",   "/briefs/generate",        "Generate brief/letter"),
            ("GET",    "/briefs/templates",       "List available templates"),
            ("GET",    "/health",                 "Health check"),
            ("POST",   "/admin/init-schema",      "One-time DB schema init"),
            ("POST",   "/admin/reset-schema",     "Drop + recreate all tables"),
        ]

        for method_str, path, _ in route_configs:
            method = getattr(apigwv2.HttpMethod, method_str)
            self.http_api.add_routes(
                path=path,
                methods=[method],
                integration=lambda_integration,
            )

        self.api_url = self.http_api.api_endpoint

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(self, "ApiUrl", value=self.api_url, export_name="CeepApiUrl")
        CfnOutput(self, "LambdaArn", value=self.api_lambda.function_arn)
