output "queue_url" { value = aws_sqs_queue.sync.url }
output "queue_arn" { value = aws_sqs_queue.sync.arn }
output "queue_id"  { value = aws_sqs_queue.sync.id }
output "dlq_arn"   { value = aws_sqs_queue.dlq.arn }
