module "database" {
  source      = "./modules/database"
  environment = var.environment
}

module "queue" {
  source      = "./modules/queue"
  environment = var.environment
}

module "frontend" {
  source      = "./modules/frontend"
  environment = var.environment
  api_lambda_url_host = module.compute.api_lambda_url_host
}

module "compute" {
  source      = "./modules/compute"
  environment = var.environment

  users_table_name    = module.database.users_table_name
  requests_table_name = module.database.requests_table_name
  users_table_arn     = module.database.users_table_arn
  requests_table_arn  = module.database.requests_table_arn

  sqs_queue_url = module.queue.queue_url
  sqs_queue_arn = module.queue.queue_arn
  sqs_queue_id  = module.queue.queue_id
  dlq_arn       = module.queue.dlq_arn

  lambda_layer_arn = var.lambda_layer_arn


  base_uri              = var.base_uri
  spotify_client_id     = var.spotify_client_id
  spotify_client_secret = var.spotify_client_secret
  posthog_api_key       = var.posthog_api_key
  jwt_secret            = var.jwt_secret
}
