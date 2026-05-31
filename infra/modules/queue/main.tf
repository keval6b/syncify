resource "aws_sqs_queue" "dlq" {
  name                      = "syncify-sync-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "sync" {
  name                       = "syncify-sync"
  visibility_timeout_seconds = 900 # 15 min — must be >= worker Lambda timeout

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}
