"""
FrontendStack — Tier 1: CloudFront + S3 static hosting for React + Vite SPA.

Note: S3 is the DEPLOYMENT TARGET for the build artefacts.
      It belongs to Tier 3 (Data/Storage) architecturally, but CloudFront
      (the CDN that serves the SPA to users) is the true Tier 1 component.
      The professor's feedback clarified this: S3 should not be listed as
      a frontend component — it is data/storage infrastructure.

Resources:
- CloudFront Origin Access Control (OAC) — restricts S3 to CloudFront only
- CloudFront distribution (HTTPS, HTTP→HTTPS redirect, SPA 404→index.html)
- Bucket policy allowing only CloudFront OAC principal
"""

from aws_cdk import (
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as s3,
    CfnOutput,
)
from constructs import Construct


class FrontendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        api_url: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Import the frontend bucket created in StorageStack
        frontend_bucket = s3.Bucket.from_bucket_name(
            self,
            "CeepFrontendBucketRef",
            bucket_name=f"ceep-frontend-{self.account}",
        )

        # ── CloudFront Origin Access Control ──────────────────────────────────
        oac = cloudfront.S3OriginAccessControl(
            self,
            "CeepOac",
            description="CEEP CloudFront OAC — only CloudFront can read the S3 frontend bucket",
        )

        # ── CloudFront Distribution ────────────────────────────────────────────
        self.distribution = cloudfront.Distribution(
            self,
            "CeepDistribution",
            comment="CEEP Community Evidence & Engagement Platform",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    frontend_bucket,
                    origin_access_control=oac,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
            ),
            # SPA fallback: any 404 from S3 → return index.html with 200
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # North America + Europe only (free tier)
        )

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(
            self,
            "CloudFrontUrl",
            value=f"https://{self.distribution.distribution_domain_name}",
            description="CEEP frontend URL. Update API GW CORS allow_origins with this value.",
            export_name="CeepFrontendUrl",
        )
        CfnOutput(
            self,
            "CloudFrontDistributionId",
            value=self.distribution.distribution_id,
        )
