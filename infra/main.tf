locals {
  # A single config serves prd and staging, selected by var.environment.
  # prd keeps the bare "syncify" prefix so its existing resources are never
  # renamed (a rename would destroy/recreate the DynamoDB tables); staging
  # gets a "syncify-stg-*" prefix. State is isolated per environment via a
  # distinct S3 backend key passed at `terraform init` (see the deploy
  # workflows), not via Terraform workspaces.
  environment = var.environment
  name_prefix = local.environment == "prd" ? "syncify" : "syncify-${local.environment}"
}

module "database" {
  source      = "./modules/database"
  name_prefix = local.name_prefix
}

module "queue" {
  source      = "./modules/queue"
  name_prefix = local.name_prefix
}

module "frontend" {
  source              = "./modules/frontend"
  name_prefix         = local.name_prefix
  api_lambda_url_host = module.compute.api_lambda_url_host
}

module "compute" {
  source      = "./modules/compute"
  name_prefix = local.name_prefix

  users_table_name    = module.database.users_table_name
  requests_table_name = module.database.requests_table_name
  users_table_arn     = module.database.users_table_arn
  requests_table_arn  = module.database.requests_table_arn

  sqs_queue_url = module.queue.queue_url
  sqs_queue_arn = module.queue.queue_arn
  sqs_queue_id  = module.queue.queue_id
  dlq_arn       = module.queue.dlq_arn

  lambda_layer_arn      = var.lambda_layer_arn
  spotify_client_id     = var.spotify_client_id
  spotify_client_secret = var.spotify_client_secret
  posthog_api_key       = var.posthog_api_key
  jwt_secret            = var.jwt_secret
}
