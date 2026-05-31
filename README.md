# Syncify

Syncify copies your Spotify "Liked Songs" to a regular playlist that can be made public and shared with friends. Spotify has never offered this natively, so here we are.

It syncs automatically every 24 hours. You can also trigger a sync manually at any time.

**Live at [syncify.keval6b.com](https://syncify.keval6b.com)**

## How it works

1. Log in with Spotify and grant access
2. Press "Enqueue Sync" to copy your liked songs into a playlist (or wait for the automatic 24-hour sync)
3. Find your new playlist in your Spotify library

Playlists are matched by name, so renaming one causes a fresh playlist to be created on the next sync, which is useful for keeping snapshots.

## Architecture

Fully serverless on AWS, running at roughly $1-5/month.

- **Frontend** — React SPA (Vite, TanStack Router/Query) deployed to S3 behind CloudFront
- **API** — FastAPI + Mangum on Lambda (arm64), behind API Gateway HTTP API (rate limited: 20 req/s, burst 50), JWT cookie sessions
- **Worker** — separate Lambda with reserved concurrency of 1, triggered by SQS
- **Scheduling** — one EventBridge Schedule per user (rate 24h) feeds the SQS queue automatically; created on signup and deleted on account deletion or revoked Spotify access
- **Database** — DynamoDB; sync request history expires after 1 year via TTL
- **IaC** — Terraform in `infra/`
- **CI/CD** — GitHub Actions deploys on push to `main` using OIDC (no stored AWS keys); frontend and Lambda layer builds run in parallel

## Deploying your own instance

### Prerequisites

- AWS account
- Spotify app ([create one here](https://developer.spotify.com/dashboard)) with a redirect URI you will add after the first deploy
- Terraform >= 1.9
- A GitHub repo with Actions enabled

### 1. Create a Terraform state bucket

Create an S3 bucket in your target region for Terraform state, then update the `bucket`, `key`, and `region` in `infra/versions.tf`.

### 2. Create a GitHub Actions deploy role

Create an IAM role trusted by GitHub Actions OIDC (`token.actions.githubusercontent.com`) and scoped to your repository and the `prd` environment. Attach the following AWS managed policies:

- `AWSLambda_FullAccess`
- `AmazonAPIGatewayAdministrator`
- `AmazonDynamoDBFullAccess`
- `AmazonSQSFullAccess`
- `AmazonS3FullAccess`
- `CloudFrontFullAccess`
- `AmazonEventBridgeFullAccess`
- `AmazonEventBridgeSchedulerFullAccess`
- `CloudWatchFullAccess`
- `AmazonSNSFullAccess`

For IAM (needed to manage Lambda execution roles), attach a custom policy scoped to `arn:aws:iam::*:role/syncify-*` covering `iam:CreateRole`, `iam:DeleteRole`, `iam:GetRole`, `iam:TagRole`, `iam:PutRolePolicy`, `iam:DeleteRolePolicy`, `iam:GetRolePolicy`, `iam:ListRolePolicies`, `iam:ListAttachedRolePolicies`, and `iam:PassRole` (the latter conditioned on `iam:PassedToService` of `lambda.amazonaws.com` and `scheduler.amazonaws.com`).

### 3. Configure GitHub environment secrets

Create a `prd` environment in your GitHub repo settings and add the following secrets:

| Secret | Description |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | ARN of the deploy role created above |
| `SPOTIPY_CLIENT_ID` | Spotify app client ID |
| `SPOTIPY_CLIENT_SECRET` | Spotify app client secret |
| `JWT_SECRET` | Secret for signing session cookies; generate with `openssl rand -hex 32` |
| `POSTHOG_API_KEY` | PostHog API key (optional; used for both frontend analytics and server-side event capture) |

### 4. Deploy

Push to `main`. The workflow builds the frontend (with PostHog key baked in as a `VITE_` variable) and the Lambda dependency layer in parallel, then runs `terraform apply`, syncs the frontend to S3, and invalidates the CloudFront cache.

### 5. First-time setup after deploy

1. **Custom domain** — add your domain and ACM certificate to the CloudFront distribution in the AWS console; Terraform is configured to ignore these fields on subsequent deploys
2. **Spotify redirect URI** — register `https://your-domain.com/api/v1/auth/callback` in your Spotify app's settings
3. **SNS alerts** — subscribe to the `syncify-alarms` SNS topic in AWS to receive email alerts for Lambda errors and worker failures
