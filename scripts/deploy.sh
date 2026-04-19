#!/usr/bin/env bash
# deploy.sh — full CEEP deployment script
#
# Prerequisites:
#   - AWS CLI configured (aws configure)
#   - Node.js 20+ and npm installed
#   - Python 3.12+ with venv support
#   - AWS CDK CLI: npm install -g aws-cdk
#
# Usage:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== CEEP Deployment ==="
echo "Root: $ROOT"

# ── Step 1: Install infra dependencies ────────────────────────────────────────
echo ""
echo "=== Step 1: Installing CDK dependencies ==="
cd "$ROOT/infrastructure"
python -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

# ── Step 2: CDK Bootstrap (first time only) ────────────────────────────────────
echo ""
echo "=== Step 2: CDK Bootstrap ==="
cdk bootstrap --ci || echo "Bootstrap already done or skipped"

# ── Step 3: Deploy all stacks ─────────────────────────────────────────────────
echo ""
echo "=== Step 3: Deploying AWS stacks ==="
cdk deploy --all --require-approval never --outputs-file "$ROOT/cdk-outputs.json"

# ── Step 4: Build and install backend dependencies ────────────────────────────
echo ""
echo "=== Step 4: Installing backend dependencies ==="
cd "$ROOT/backend"
pip install -q -r requirements.txt

# ── Step 5: Build frontend ────────────────────────────────────────────────────
echo ""
echo "=== Step 5: Building frontend ==="
cd "$ROOT/frontend"
npm ci --silent
npm run build

# ── Step 6: Upload frontend to S3 ─────────────────────────────────────────────
echo ""
echo "=== Step 6: Uploading frontend to S3 ==="
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
FRONTEND_BUCKET="ceep-frontend-${ACCOUNT_ID}"
aws s3 sync dist/ "s3://${FRONTEND_BUCKET}/" --delete --cache-control "public, max-age=31536000, immutable"
# HTML files: no cache
aws s3 cp dist/index.html "s3://${FRONTEND_BUCKET}/index.html" --cache-control "no-cache, no-store"

# ── Step 7: Invalidate CloudFront ─────────────────────────────────────────────
echo ""
echo "=== Step 7: CloudFront cache invalidation ==="
DIST_ID=$(jq -r '.CeepFrontendStack.CloudFrontDistributionId' "$ROOT/cdk-outputs.json")
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*"

# ── Step 8: Initialise DB schema ──────────────────────────────────────────────
echo ""
echo "=== Step 8: Initialising database schema ==="
echo "NOTE: Run manually inside the Lambda VPC or via a bastion host:"
echo "  cd backend && python -m app.core.schema"

# ── Step 9: Upload Glue scripts ───────────────────────────────────────────────
echo ""
echo "=== Step 9: Uploading Glue scripts ==="
PUBLIC_BUCKET="ceep-public-docs-${ACCOUNT_ID}"
aws s3 cp "$ROOT/etl/glue_jobs/" "s3://${PUBLIC_BUCKET}/glue-scripts/" --recursive

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
