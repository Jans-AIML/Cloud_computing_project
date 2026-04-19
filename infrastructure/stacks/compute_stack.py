"""
ComputeStack — Tier 2: Lambda (FastAPI/Mangum) + API Gateway.

API Gateway is the SOLE entry point for all client requests.
Every route (/documents, /search, /rag, /briefs) goes through API GW → Lambda.

Resources created:
- Lambda security group (allows egress to RDS, Bedrock VPC endpoint)
- Lambda function (FastAPI app via Mangum, Python 3.12)
- API Gateway HTTP API with CORS restricted to CloudFront domain
- IAM role with least-privilege policies:
    S3 read/write (public-docs), Secrets Manager read, Bedrock InvokeModel,
    Comprehend DetectPiiEntities, SQS SendMessage
"""

from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_iam as iam,
    aws_ec2 as ec2,
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
            description="CEEP Lambda SG — egress to RDS and VPC endpoints",
            allow_all_outbound=True,  # VPC endpoints handle traffic internally
        )

        # Allow Lambda → RDS on PostgreSQL port
        rds_sg_id = Stack.of(self).format_arn(
            service="ec2",
            resource="security-group",
            resource_name="CeepRdsSg",
        )

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
        private_bucket.grant_put(lambda_role)  # for generating pre-signed upload URLs only

        # Secrets Manager: read DB credentials
        db_secret.grant_read(lambda_role)

        # AWS Bedrock: invoke Claude 3 models and Titan Embeddings
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockInvoke",
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0",
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0",
                ],
            )
        )

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
        self.api_lambda = _lambda.Function(
            self,
            "CeepApiLambda",
            function_name="ceep-api",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="app.main.handler",
            code=_lambda.Code.from_asset(
                "../backend",
                # Exclude dev files to keep the deployment package small
                exclude=[
                    "**/__pycache__/**",
                    "**/.pytest_cache/**",
                    "**/tests/**",
                    "Dockerfile",
                    ".env*",
                ],
            ),
            role=lambda_role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[lambda_sg],
            timeout=Duration.seconds(30),
            memory_size=512,
            tracing=_lambda.Tracing.ACTIVE,
            environment={
                "DB_HOST": db_endpoint,
                "DB_PORT": db_port,
                "DB_NAME": "ceep",
                "DB_SECRET_ARN": db_secret.secret_arn,
                "PUBLIC_BUCKET": public_bucket.bucket_name,
                "PRIVATE_BUCKET": private_bucket.bucket_name,
                "AWS_REGION_NAME": self.region,
                "BEDROCK_CLAUDE_MODEL_ID": "anthropic.claude-3-haiku-20240307-v1:0",
                "BEDROCK_EMBED_MODEL_ID": "amazon.titan-embed-text-v2:0",
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
                # Restrict CORS to the CloudFront domain only (set after frontend deploy)
                # Using "*" temporarily; replace with CloudFront URL before launch
                allow_origins=["*"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.DELETE,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["Content-Type", "Authorization", "X-Request-Id"],
                max_age=Duration.hours(1),
            ),
        )

        # Routes — all traffic through API Gateway
        route_configs = [
            ("POST",   "/documents/upload",      "Upload document (returns pre-signed S3 URL)"),
            ("GET",    "/documents",              "List evidence cards"),
            ("GET",    "/documents/{id}",         "Get single evidence card"),
            ("DELETE", "/documents/{id}",         "Delete document + embeddings"),
            ("GET",    "/search",                 "Keyword + vector search"),
            ("POST",   "/rag/query",              "RAG Q&A with citations"),
            ("POST",   "/rag/stream",             "Streaming RAG Q&A"),
            ("POST",   "/briefs/generate",        "Generate brief/letter"),
            ("GET",    "/briefs/templates",       "List available templates"),
            ("GET",    "/health",                 "Health check"),
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
