resource "aws_dynamodb_table" "users" {
  name         = "${var.name_prefix}-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "userId"

  attribute {
    name = "userId"
    type = "S"
  }
}

resource "aws_dynamodb_table" "sync_requests" {
  name         = "${var.name_prefix}-sync-requests"
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

  attribute {
    name = "createdAt"
    type = "S"
  }

  # Sparse GSI for "latest N requests per user" — lock items omit createdAt
  # and are therefore excluded from the index.
  global_secondary_index {
    name            = "byCreatedAt"
    hash_key        = "userId"
    range_key       = "createdAt"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }
}
