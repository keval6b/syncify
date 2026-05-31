resource "aws_dynamodb_table" "users" {
  name         = "syncify-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "userId"

  attribute {
    name = "userId"
    type = "S"
  }

  tags = {
    service     = "syncify"
    environment = var.environment
  }
}

resource "aws_dynamodb_table" "sync_requests" {
  name         = "syncify-sync-requests"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "userId"
  range_key    = "requestId"

  attribute {
    name = "userId"
    type = "S"
  }

  attribute {
    name = "requestId"
    type = "S"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  tags = {
    service     = "syncify"
    environment = var.environment
  }
}
