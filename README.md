# Syncify

A tool that copies your "Liked Songs" to a regular playlist that you can make public and/or share with your friends.

For some reason doing this has always been impossible; it has bugged me for years. I finally decided to fix it myself.

## Usage

1. Go to [https://syncify.keval6b.com](https://syncify.keval6b.com)
2. Press "Login with Spotify"
3. When prompted, allow access
4. Press the "Enqueue Sync" button
5. Wait (it takes about 20 seconds to synchronize ~1250 Liked Songs)
6. Check your library for your new playlist(s)

The tool updates the same playlists by name every time you sync, so if you want to keep an iteration just rename it and a new one will be created next time.

While you have an account, your liked songs are synced automatically every 24 hours.

## Architecture

Syncify runs on AWS serverless infrastructure:

- **Frontend** — React SPA on S3 behind CloudFront
- **API** — FastAPI on Lambda (arm64), session auth via signed JWT cookies
- **Worker** — separate Lambda (reserved concurrency 1) triggered by SQS, handles the Spotify sync
- **Scheduling** — per-user EventBridge Schedule (rate 24h) sends an SQS message for each user automatically
- **Database** — DynamoDB (users + sync requests, 1 year TTL on requests)
- **IaC** — Terraform in `infra/`
- **CI/CD** — GitHub Actions deploys on push to `main`

## Deploying

Set the following secrets in the `prd` GitHub environment:

| Secret | Description |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | IAM role ARN for the GitHub Actions OIDC deploy role |
| `SPOTIPY_CLIENT_ID` | Spotify app client ID |
| `SPOTIPY_CLIENT_SECRET` | Spotify app client secret |
| `JWT_SECRET` | Random secret for signing session cookies (`openssl rand -hex 32`) |
| `POSTHOG_API_KEY` | PostHog API key (optional) |

Push to `main` to deploy. On first deploy:

1. Create the Terraform state bucket (`syncify-tfstate-661355305324-eu-west-2-an`) if it doesn't exist
2. Add your custom domain and ACM certificate to the CloudFront distribution manually after the first apply
3. Register `https://syncify.keval6b.com/api/v1/auth/callback` as a redirect URI in the Spotify Developer Dashboard
