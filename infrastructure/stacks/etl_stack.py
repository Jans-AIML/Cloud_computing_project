"""
EtlStack — Tier 2 (workers): AWS Glue ETL jobs + SQS + Comprehend permissions.

Flow:
  S3 private bucket (raw upload)
    → S3 Event Notification → SQS queue
    → Glue Job Trigger (polls SQS)
    → Glue Job: pii_redactor  → chunker_embedder → index_loader
    → RDS PostgreSQL (evidence cards + pgvector embeddings)

Resources:
- SQS queue (document-ingest-queue) with DLQ
- Glue IAM role with Comprehend + S3 + Bedrock + RDS permissions
- Glue jobs (PySpark scripts in s3://ceep-public-docs/glue-scripts/)
- S3 event notification (private bucket → SQS)
"""

from aws_cdk import (
    Stack,
    Duration,
    aws_sqs as sqs,
    aws_glue as glue,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_secretsmanager as secretsmanager,
    aws_ec2 as ec2,
    CfnOutput,
)
from constructs import Construct


class EtlStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        private_bucket: s3.IBucket,
        public_bucket: s3.IBucket,
        db_secret: secretsmanager.ISecret,
        db_endpoint: str,
        vpc: ec2.IVpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── SQS Dead-Letter Queue ─────────────────────────────────────────────
        dlq = sqs.Queue(
            self,
            "CeepIngestDlq",
            queue_name="ceep-ingest-dlq",
            retention_period=Duration.days(14),
        )

        # ── SQS Ingest Queue ──────────────────────────────────────────────────
        # Lambda writes a message here when a document upload is confirmed.
        # The Glue trigger polls this queue.
        self.ingest_queue = sqs.Queue(
            self,
            "CeepIngestQueue",
            queue_name="ceep-document-ingest",
            visibility_timeout=Duration.minutes(15),   # match Glue job timeout
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dlq,
            ),
        )

        # ── Glue IAM Role ─────────────────────────────────────────────────────
        glue_role = iam.Role(
            self,
            "CeepGlueRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSGlueServiceRole"
                )
            ],
        )

        # S3: read private bucket, read/write public-docs bucket
        private_bucket.grant_read(glue_role)
        public_bucket.grant_read_write(glue_role)

        # Secrets Manager: read DB credentials
        db_secret.grant_read(glue_role)

        # SQS: receive + delete messages
        self.ingest_queue.grant_consume_messages(glue_role)

        # Comprehend: PII entity detection
        glue_role.add_to_policy(
            iam.PolicyStatement(
                sid="ComprehendPii",
                actions=[
                    "comprehend:DetectPiiEntities",
                    "comprehend:ContainsPiiEntities",
                ],
                resources=["*"],  # Comprehend does not support resource-level restrictions
            )
        )

        # Bedrock: generate embeddings (Titan Embeddings v2)
        glue_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockEmbed",
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
                ],
            )
        )

        # Glue scripts live in public-docs bucket under glue-scripts/
        scripts_prefix = f"s3://{public_bucket.bucket_name}/glue-scripts"

        # ── Glue Job: PII Redactor ─────────────────────────────────────────────
        # Reads raw document from private S3, redacts PII, writes clean text to public-docs.
        glue.CfnJob(
            self,
            "CeepPiiRedactorJob",
            name="ceep-pii-redactor",
            role=glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"{scripts_prefix}/pii_redactor.py",
            ),
            glue_version="4.0",
            number_of_workers=2,
            worker_type="G.1X",
            max_retries=1,
            timeout=15,
            default_arguments={
                "--PRIVATE_BUCKET": private_bucket.bucket_name,
                "--PUBLIC_BUCKET": public_bucket.bucket_name,
                "--DB_SECRET_ARN": db_secret.secret_arn,
                "--DB_HOST": db_endpoint,
                "--DB_NAME": "ceep",
                "--AWS_REGION": self.region,
                "--enable-job-bookmarks": "enable",
                "--job-language": "python",
                "--TempDir": f"s3://{public_bucket.bucket_name}/glue-tmp/",
            },
            description="Step 1: Detect and redact PII from raw uploaded documents",
        )

        # ── Glue Job: Chunker + Embedder ──────────────────────────────────────
        # Reads clean text, splits into 400-token chunks, generates Titan embeddings.
        glue.CfnJob(
            self,
            "CeepChunkerEmbedderJob",
            name="ceep-chunker-embedder",
            role=glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"{scripts_prefix}/chunker_embedder.py",
            ),
            glue_version="4.0",
            number_of_workers=2,
            worker_type="G.1X",
            max_retries=1,
            timeout=30,
            default_arguments={
                "--PUBLIC_BUCKET": public_bucket.bucket_name,
                "--DB_SECRET_ARN": db_secret.secret_arn,
                "--DB_HOST": db_endpoint,
                "--DB_NAME": "ceep",
                "--AWS_REGION": self.region,
                "--BEDROCK_EMBED_MODEL_ID": "amazon.titan-embed-text-v2:0",
                "--CHUNK_SIZE": "400",
                "--CHUNK_OVERLAP": "50",
                "--enable-job-bookmarks": "enable",
                "--TempDir": f"s3://{public_bucket.bucket_name}/glue-tmp/",
            },
            description="Step 2: Chunk clean text and generate vector embeddings",
        )

        # ── Glue Workflow: chains the two jobs ────────────────────────────────
        glue.CfnWorkflow(
            self,
            "CeepIngestWorkflow",
            name="ceep-ingest-workflow",
            description="CEEP ETL: PII redact → chunk → embed → index",
        )

        CfnOutput(self, "IngestQueueUrl", value=self.ingest_queue.queue_url)
        CfnOutput(self, "IngestQueueArn", value=self.ingest_queue.queue_arn)
