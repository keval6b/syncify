output "users_table_name" { value = aws_dynamodb_table.users.name }
output "users_table_arn"  { value = aws_dynamodb_table.users.arn }
output "requests_table_name" { value = aws_dynamodb_table.sync_requests.name }
output "requests_table_arn"  { value = aws_dynamodb_table.sync_requests.arn }
