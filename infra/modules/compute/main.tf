locals {
  common_env = {
    SPOTIPY_CLIENT_ID     = var.spotify_client_id
    SPOTIPY_CLIENT_SECRET = var.spotify_client_secret
    POSTHOG_API_KEY       = var.posthog_api_key
    JWT_SECRET            = var.jwt_secret
    USERS_TABLE           = var.users_table_name
    REQUESTS_TABLE        = var.requests_table_name
    SQS_QUEUE_URL         = var.sqs_queue_url
    SQS_QUEUE_ARN         = var.sqs_queue_arn
    SCHEDULE_ROLE_ARN     = aws_iam_role.schedule_executor.arn
    SCHEDULE_GROUP        = aws_scheduler_schedule_group.users.name
    CHECKPOINT_BUCKET     = aws_s3_bucket.checkpoints.bucket
  }

  worker_env = merge(local.common_env, {
    DURABLE_FUNCTION_NAME = aws_lambda_alias.sync.arn
  })

  # Lambda source: zip the src/ directory (deps come from the layer)
  source_dir = "${path.root}/../backend/src"
}

data "archive_file" "source" {
  type        = "zip"
  source_dir  = local.source_dir
  output_path = "${path.module}/source.zip"
  excludes = ["**/__pycache__", "**/__pycache__/**", "**/*.pyc"]
}

# --- CloudWatch Log Groups (created ahead of Lambdas to enforce retention) ---
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.name_prefix}-api"
  retention_in_days = 90
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${var.name_prefix}-worker"
  retention_in_days = 90
}

resource "aws_cloudwatch_log_group" "sync" {
  name              = "/aws/lambda/${var.name_prefix}-sync"
  retention_in_days = 90
}

# --- API Lambda ---
resource "aws_lambda_function" "api" {
  function_name    = "${var.name_prefix}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "syncify2.api.lambda_handler.handler"
  timeout          = 29 # API Gateway HTTP API caps integration timeout at 30s
  memory_size      = 128
  filename         = data.archive_file.source.output_path
  source_code_hash = data.archive_file.source.output_base64sha256
  layers           = [var.lambda_layer_arn]
  environment { variables = local.common_env }
  depends_on = [aws_cloudwatch_log_group.api]
}

# --- API Gateway HTTP API ---
resource "aws_apigatewayv2_api" "api" {
  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "api" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 20
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# SQS invokes this function. It only starts the durable execution; the mapping
# itself cannot host an execution longer than 15 minutes.
resource "aws_lambda_function" "worker" {
  function_name    = "${var.name_prefix}-worker"
  role             = aws_iam_role.worker.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "syncify2.worker.lambda_handler.handler"
  timeout          = 30
  memory_size      = 128
  filename         = data.archive_file.source.output_path
  source_code_hash = data.archive_file.source.output_base64sha256
  layers           = [var.lambda_layer_arn]
  environment { variables = local.worker_env }
  depends_on = [aws_cloudwatch_log_group.worker]
}

resource "aws_lambda_function" "sync" {
  function_name    = "${var.name_prefix}-sync"
  role             = aws_iam_role.worker.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "syncify2.worker.durable_handler.handler"
  timeout          = 900
  memory_size      = 128
  filename         = data.archive_file.source.output_path
  source_code_hash = data.archive_file.source.output_base64sha256
  layers           = [var.lambda_layer_arn]
  publish          = true
  environment { variables = local.common_env }

  durable_config {
    execution_timeout = 21600
    retention_period  = 1
  }

  timeouts {
    delete = "60m"
  }

  depends_on = [aws_cloudwatch_log_group.sync]
}

resource "aws_lambda_alias" "sync" {
  name             = "live"
  function_name    = aws_lambda_function.sync.function_name
  function_version = aws_lambda_function.sync.version
}

resource "aws_s3_bucket" "checkpoints" {
  bucket = "${var.name_prefix}-checkpoints-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "checkpoints" {
  bucket                  = aws_s3_bucket.checkpoints.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "checkpoints" {
  bucket = aws_s3_bucket.checkpoints.id

  rule {
    id     = "expire-slices"
    status = "Enabled"

    filter {}

    expiration {
      days = 7
    }
  }
}

resource "aws_lambda_event_source_mapping" "worker_sqs" {
  event_source_arn                   = var.sqs_queue_arn
  function_name                      = aws_lambda_function.worker.arn
  batch_size                         = 1
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]
}

# --- EventBridge Schedule Group (one schedule per user lives here) ---
resource "aws_scheduler_schedule_group" "users" {
  name = "${var.name_prefix}-users"
}

# --- CloudWatch Alarms ---
resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${var.name_prefix}-dlq-depth"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = "${var.name_prefix}-sync-dlq" }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_description   = "Worker DLQ has messages — sync failed 3 times"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${var.name_prefix}-api-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_description   = "API Lambda threw an error"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "sync_failures" {
  alarm_name          = "${var.name_prefix}-sync-failures"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.sync.function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_description   = "Durable sync execution failed"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"
}
