resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name_prefix}-sync-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "sync" {
  name                       = "${var.name_prefix}-sync"
  visibility_timeout_seconds = 960 # 16 min: worker timeout (15 min) + 1 min buffer

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}
