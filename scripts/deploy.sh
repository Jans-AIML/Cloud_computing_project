#!/usr/bin/env bash
# deploy.sh — full CEEP cloud deployment
#
# Prerequisites:
#   aws configure (or AWS_* env vars set)
#   npm install -g aws-cdk  (already done if you ran make deploy-infra)
#
# Usage (from project root):
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"

echo "========================================"
echo "  CEEP Cloud Deployment"
echo "  Account: ${ACCOUNT_ID}  Region: ${REGION}"
echo "========================================"

# ── Step 1: Build frontend with production API URL placeholder ────────────────
echo ""
echo ">>> Step 1: Building React frontend..."
cd "$ROOT/frontend"
npm ci --silent

# We build twice if needed: first deploy infra to get the API URL, then set it.
# On first run, VITE_API_URL may not exist yet — that is OK, we update it after.
OUTPUTS="$ROOT/cdk-outputs.json"
if [[ -f "$OUTPUTS" ]]; then
  API_URL=$(jq -r '.CeepComputeStack.ApiUrl // empty' "$OUTPUTS" 2>/dev/null || echo "")
  if [[ -n "$API_URL" ]]; then
    echo "    API URL from previous deploy: $API_URL"
    echo "VITE_API_URL=${API_URL}" > .env.production
  fi
fi
npm run build

# ── Step 2: CDK bootstrap (safe to re-run; no-op if already done) ─────────────
echo ""
echo ">>> Step 2: CDK bootstrap..."
cd "$ROOT/infrastructure"
cdk bootstrap "aws://${ACCOUNT_ID}/${REGION}" --ci 2>&1 | grep -v "^$" | head -10

# ── Step 3: Deploy all CDK stacks ─────────────────────────────────────────────
echo ""
echo ">>> Step 3: Deploying CDK stacks (StorageStack → ComputeStack → EtlStack → FrontendStack)..."
cd "$ROOT/infrastructure"
cdk deploy --all \
  --require-approval never \
  --outputs-file "$OUTPUTS" \
  2>&1 | grep -E "^(✅|❌|CeepStack|Update|CREATE|ROLLBACK|Error)" || true

echo ""
echo "Stack outputs saved to cdk-outputs.json"

# ── Step 4: Re-build frontend with real API URL ────────────────────────────────
echo ""
echo ">>> Step 4: Re-building frontend with live API Gateway URL..."
API_URL=$(jq -r '.CeepComputeStack.ApiUrl // empty' "$OUTPUTS")
CF_URL=$(jq -r '.CeepFrontendStack.CloudFrontUrl // empty' "$OUTPUTS")

if [[ -z "$API_URL" ]]; then
  echo "ERROR: Could not read ApiGatewayUrl from cdk-outputs.json" >&2
  exit 1
fi

echo "    API Gateway: $API_URL"
echo "    CloudFront:  $CF_URL"

cd "$ROOT/frontend"
echo "VITE_API_URL=${API_URL}" > .env.production
npm run build

# ── Step 5: Sync frontend build to S3 ─────────────────────────────────────────
echo ""
echo ">>> Step 5: Uploading frontend to S3..."
FRONTEND_BUCKET="ceep-frontend-${ACCOUNT_ID}"

# Assets (hashed filenames) — long cache
aws s3 sync dist/assets "s3://${FRONTEND_BUCKET}/assets/" \
  --delete \
  --cache-control "public, max-age=31536000, immutable" \
  --region "$REGION" \
  --quiet

# HTML — no cache (SPA entry point must always be fresh)
aws s3 cp dist/index.html "s3://${FRONTEND_BUCKET}/index.html" \
  --cache-control "no-cache, no-store, must-revalidate" \
  --region "$REGION"

echo "    Frontend uploaded."

# ── Step 6: Invalidate CloudFront ─────────────────────────────────────────────
echo ""
echo ">>> Step 6: Invalidating CloudFront cache..."
DIST_ID=$(jq -r '.CeepFrontendStack.CloudFrontDistributionId // empty' "$OUTPUTS")
if [[ -n "$DIST_ID" ]]; then
  aws cloudfront create-invalidation \
    --distribution-id "$DIST_ID" \
    --paths "/*" \
    --region "$REGION" \
    --query 'Invalidation.Id' \
    --output text
  echo "    Invalidation created."
fi

# ── Step 7: Upload Glue ETL scripts ───────────────────────────────────────────
echo ""
echo ">>> Step 7: Uploading Glue ETL scripts..."
PUBLIC_BUCKET="ceep-public-docs-${ACCOUNT_ID}"
aws s3 cp "$ROOT/etl/glue_jobs/" "s3://${PUBLIC_BUCKET}/glue-scripts/" \
  --recursive --quiet --region "$REGION"
echo "    Glue scripts uploaded."

# ── Step 8: Initialise DB schema via Lambda invoke ────────────────────────────
echo ""
echo ">>> Step 8: Running DB schema init via Lambda..."
INIT_RESULT=$(aws lambda invoke \
  --function-name ceep-api \
  --cli-binary-format raw-in-base64-out \
  --payload '{"path":"/admin/init-schema","httpMethod":"POST","headers":{},"queryStringParameters":null,"body":null,"isBase64Encoded":false}' \
  --region "$REGION" \
  /tmp/ceep-lambda-init.json 2>&1 || true)

echo "    Response: $(cat /tmp/ceep-lambda-init.json 2>/dev/null || echo 'see CloudWatch logs')"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  DEPLOY COMPLETE"
echo "  App URL: https://${CF_URL}"
echo "  API URL: ${API_URL}"
echo "========================================"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== Deployment complete ==="
FRONTEND_URL=$(jq -r '.CeepFrontendStack.CloudFrontUrl' "$ROOT/cdk-outputs.json")
API_URL=$(jq -r '.CeepComputeStack.ApiUrl' "$ROOT/cdk-outputs.json")
echo "Frontend: $FRONTEND_URL"
echo "API:      $API_URL"
echo ""
echo "Next steps:"
echo "  1. Update the CORS allow_origins in ComputeStack to: $FRONTEND_URL"
echo "  2. Set VITE_API_URL=$API_URL in frontend/.env.production"
echo "  3. Run 'cd frontend && npm run build' and re-run Step 6 & 7"
echo "  4. Seed the corpus: cd scripts && python seed_corpus.py"
