variable "aws_region" {
  default = "eu-west-2"
}

variable "environment" {
  description = "Deployment environment: prd or stg. Drives the resource name prefix."
  default     = "prd"
}

variable "lambda_layer_arn" {
  description = "ARN of the published Lambda layer containing Python dependencies"
}

# Spotify creds and the JWT secret now come from SSM (see data sources in
# main.tf); only the non-sensitive PostHog key remains a Terraform variable.
variable "posthog_api_key" {
  default = ""
}
