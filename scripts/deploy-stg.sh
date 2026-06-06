#!/usr/bin/env bash
# Deploy the current working tree to the syncify-stg-* stack:
#   1. tofu apply against the staging state key (in-place updates to the two Lambdas)
#   2. build the frontend (no PostHog so stg events don't pollute prod analytics)
#   3. sync the dist/ bundle to the stg SPA bucket and invalidate CloudFront
#
# Pre-reqs: valid AWS creds for the syncify account, infra/stg.auto.tfvars present,
# pnpm and tofu on PATH.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f infra/stg.auto.tfvars ]]; then
    echo "missing infra/stg.auto.tfvars; create it before deploying to stg" >&2
    exit 1
fi

aws sts get-caller-identity --query Arn --output text >/dev/null

echo "==> build lambda layer"
uv export --no-dev --no-editable --no-emit-project \
    -o /tmp/requirements.txt \
    --project "$repo_root/backend" >/dev/null
uv pip install -r /tmp/requirements.txt \
    --python-platform manylinux2014_aarch64 \
    --python 3.13 \
    --only-binary=:all: \
    --target "$repo_root/backend/lambda_layer/python" \
    --quiet
(cd "$repo_root/backend/lambda_layer" && zip -r "$repo_root/lambda_layer.zip" . -q)

echo "==> publish lambda layer"
layer_arn=$(aws lambda publish-layer-version \
    --layer-name syncify-deps \
    --zip-file "fileb://$repo_root/lambda_layer.zip" \
    --compatible-runtimes python3.13 \
    --compatible-architectures arm64 \
    --query LayerVersionArn --output text)
echo "    $layer_arn"
sed -i "s|lambda_layer_arn = .*|lambda_layer_arn = \"$layer_arn\"|" "$repo_root/infra/stg.auto.tfvars"

echo "==> tofu init (stg state key)"
tofu -chdir=infra init -reconfigure -input=false \
    -backend-config="key=syncify-stg/terraform.tfstate" >/dev/null

echo "==> tofu apply"
tofu -chdir=infra apply -auto-approve -input=false

bucket="$(tofu -chdir=infra output -raw s3_bucket_name)"
distribution_id="$(tofu -chdir=infra output -raw cloudfront_distribution_id)"
domain="$(tofu -chdir=infra output -raw cloudfront_domain)"

echo "==> build frontend"
(
    cd frontend
    pnpm install --frozen-lockfile
    VITE_POSTHOG_API_KEY="" pnpm run build
)

echo "==> sync to s3://${bucket}/"
aws s3 sync frontend/dist/ "s3://${bucket}/" --delete

echo "==> invalidate CloudFront ${distribution_id}"
aws cloudfront create-invalidation \
    --distribution-id "$distribution_id" \
    --paths "/*" \
    --query 'Invalidation.Id' --output text

echo
echo "stg live at https://${domain}"
