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
  }

  # Lambda source: zip the src/ directory (deps come from the layer)
  source_dir = "${path.root}/../backend/src"
}

data "archive_file" "source" {
  type        = "zip"
  source_dir  = local.source_dir
  output_path = "${path.module}/source.zip"
}

# --- API Lambda ---
resource "aws_lambda_function" "api" {
  function_name    = "syncify-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "syncify2.api.lambda_handler.handler"
  timeout          = 29
  memory_size      = 512
  filename         = data.archive_file.source.output_path
  source_code_hash = data.archive_file.source.output_base64sha256
  layers           = [var.lambda_layer_arn]
  environment { variables = local.common_env }
}

# --- API Gateway HTTP API ---
resource "aws_apigatewayv2_api" "api" {
  name          = "syncify-api"
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

# --- Worker Lambda ---
resource "aws_lambda_function" "worker" {
  function_name                  = "syncify-worker"
  role                           = aws_iam_role.worker.arn
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  handler                        = "syncify2.worker.lambda_handler.handler"
  timeout                        = 900 # 15 min
  memory_size                    = 512
  reserved_concurrent_executions = 1
  filename                       = data.archive_file.source.output_path
  source_code_hash               = data.archive_file.source.output_base64sha256
  layers                         = [var.lambda_layer_arn]
  environment { variables = local.common_env }
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
  name = "syncify-users"
}

# --- CloudWatch Alarms ---
resource "aws_sns_topic" "alarms" {
  name = "syncify-alarms"
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "syncify-dlq-depth"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = "syncify-sync-dlq" }
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
  alarm_name          = "syncify-api-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_description   = "API Lambda error rate elevated"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "worker_duration" {
  alarm_name          = "syncify-worker-duration"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = aws_lambda_function.worker.function_name }
  extended_statistic  = "p99"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 720000 # 12 min in ms
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_description   = "Worker sync approaching Lambda timeout"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"
}
