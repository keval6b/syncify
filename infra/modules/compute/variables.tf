variable "users_table_name" {}
variable "users_table_arn" {}
variable "requests_table_name" {}
variable "requests_table_arn" {}

variable "sqs_queue_url" {}
variable "sqs_queue_arn" {}
variable "sqs_queue_id" {}
variable "dlq_arn" {}

variable "lambda_layer_arn" {}

variable "spotify_client_id" { sensitive = true }
variable "spotify_client_secret" { sensitive = true }
variable "posthog_api_key" { sensitive = true }
variable "jwt_secret" { sensitive = true }
