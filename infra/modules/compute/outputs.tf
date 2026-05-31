output "api_lambda_url"      { value = aws_lambda_function_url.api.function_url }
output "api_lambda_url_host" { value = replace(aws_lambda_function_url.api.function_url, "https://", "") }
