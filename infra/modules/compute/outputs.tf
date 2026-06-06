output "api_url" { value = aws_apigatewayv2_api.api.api_endpoint }
output "api_lambda_url_host" { value = trimprefix(aws_apigatewayv2_api.api.api_endpoint, "https://") }
