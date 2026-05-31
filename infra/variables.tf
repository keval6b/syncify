variable "aws_region" {
  default = "eu-west-2"
}

variable "environment" {
  default = "prd"
}

variable "lambda_layer_arn" {
  description = "ARN of the published Lambda layer containing Python dependencies"
}

variable "spotify_client_id" {
  sensitive = true
}

variable "spotify_client_secret" {
  sensitive = true
}

variable "posthog_api_key" {
  sensitive = true
  default   = ""
}

variable "jwt_secret" {
  sensitive = true
}
