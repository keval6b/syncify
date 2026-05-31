terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-west-2"
}

data "aws_caller_identity" "current" {}

# GitHub OIDC provider (one per account — import if it already exists)
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_role" "deploy" {
  name = "syncify-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:yottapanda/syncify:environment:prd" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [

      # --- Terraform state ---
      {
        Sid      = "TerraformState"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [
          "arn:aws:s3:::syncify-tfstate-661355305324-eu-west-2-an",
          "arn:aws:s3:::syncify-tfstate-661355305324-eu-west-2-an/*",
        ]
      },

      # --- S3 (SPA bucket — random suffix, scoped by prefix) ---
      {
        Sid    = "S3SpaBucket"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket", "s3:DeleteBucket", "s3:ListBucket",
          "s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:PutBucketVersioning",
          "s3:GetBucketPublicAccessBlock", "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketPolicy", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy",
          "s3:GetBucketTagging", "s3:PutBucketTagging",
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
          "s3:GetEncryptionConfiguration",
        ]
        Resource = [
          "arn:aws:s3:::syncify-spa-*",
          "arn:aws:s3:::syncify-spa-*/*",
        ]
      },

      # --- Lambda functions ---
      {
        Sid    = "LambdaFunctions"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction", "lambda:DeleteFunction",
          "lambda:GetFunction", "lambda:GetFunctionConfiguration",
          "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
          "lambda:AddPermission", "lambda:RemovePermission",
          "lambda:CreateFunctionUrlConfig", "lambda:UpdateFunctionUrlConfig",
          "lambda:GetFunctionUrlConfig", "lambda:DeleteFunctionUrlConfig",
          "lambda:CreateEventSourceMapping", "lambda:UpdateEventSourceMapping",
          "lambda:DeleteEventSourceMapping", "lambda:GetEventSourceMapping",
          "lambda:ListEventSourceMappings",
          "lambda:TagResource", "lambda:ListTags",
          "lambda:GetPolicy",
        ]
        Resource = [
          "arn:aws:lambda:eu-west-2:${data.aws_caller_identity.current.account_id}:function:syncify-*",
          "arn:aws:lambda:eu-west-2:${data.aws_caller_identity.current.account_id}:event-source-mapping:*",
        ]
      },
      {
        Sid    = "LambdaLayers"
        Effect = "Allow"
        Action = [
          "lambda:PublishLayerVersion", "lambda:GetLayerVersion",
          "lambda:DeleteLayerVersion", "lambda:ListLayerVersions",
        ]
        Resource = "arn:aws:lambda:eu-west-2:${data.aws_caller_identity.current.account_id}:layer:syncify-*"
      },

      # --- IAM (scoped to syncify roles only) ---
      {
        Sid    = "IAMRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
          "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy", "iam:ListRolePolicies",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:UpdateAssumeRolePolicy",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/syncify-*"
      },
      {
        Sid      = "IAMPassRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/syncify-*"
      },

      # --- DynamoDB ---
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:CreateTable", "dynamodb:DeleteTable",
          "dynamodb:DescribeTable", "dynamodb:UpdateTable",
          "dynamodb:UpdateTimeToLive", "dynamodb:DescribeTimeToLive",
          "dynamodb:TagResource", "dynamodb:UntagResource", "dynamodb:ListTagsOfResource",
        ]
        Resource = "arn:aws:dynamodb:eu-west-2:${data.aws_caller_identity.current.account_id}:table/syncify-*"
      },

      # --- SQS ---
      {
        Sid    = "SQS"
        Effect = "Allow"
        Action = [
          "sqs:CreateQueue", "sqs:DeleteQueue",
          "sqs:GetQueueAttributes", "sqs:SetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:TagQueue", "sqs:UntagQueue", "sqs:ListQueueTags",
        ]
        Resource = "arn:aws:sqs:eu-west-2:${data.aws_caller_identity.current.account_id}:syncify-*"
      },

      # --- CloudFront ---
      {
        Sid    = "CloudFront"
        Effect = "Allow"
        Action = [
          "cloudfront:CreateDistribution", "cloudfront:UpdateDistribution",
          "cloudfront:DeleteDistribution", "cloudfront:GetDistribution",
          "cloudfront:GetDistributionConfig",
          "cloudfront:CreateOriginAccessControl", "cloudfront:UpdateOriginAccessControl",
          "cloudfront:DeleteOriginAccessControl", "cloudfront:GetOriginAccessControl",
          "cloudfront:ListOriginAccessControls",
          "cloudfront:CreateInvalidation",
          "cloudfront:TagResource", "cloudfront:UntagResource", "cloudfront:ListTagsForResource",
        ]
        Resource = "*" # CloudFront ARNs are global and not predictable at policy-write time
      },

      # --- EventBridge rules (warm ping) ---
      {
        Sid    = "EventBridgeRules"
        Effect = "Allow"
        Action = [
          "events:PutRule", "events:DeleteRule", "events:DescribeRule",
          "events:PutTargets", "events:RemoveTargets", "events:ListTargetsByRule",
          "events:TagResource", "events:UntagResource", "events:ListTagsForResource",
        ]
        Resource = "arn:aws:events:eu-west-2:${data.aws_caller_identity.current.account_id}:rule/syncify-*"
      },

      # --- EventBridge Scheduler (schedule group only — individual schedules are user-managed) ---
      {
        Sid    = "Scheduler"
        Effect = "Allow"
        Action = [
          "scheduler:CreateScheduleGroup", "scheduler:DeleteScheduleGroup",
          "scheduler:GetScheduleGroup", "scheduler:ListScheduleGroups",
          "scheduler:TagResource", "scheduler:UntagResource", "scheduler:ListTagsForResource",
        ]
        Resource = "arn:aws:scheduler:eu-west-2:${data.aws_caller_identity.current.account_id}:schedule-group/syncify-*"
      },

      # --- CloudWatch alarms ---
      {
        Sid    = "CloudWatch"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:DescribeAlarms",
          "cloudwatch:TagResource", "cloudwatch:UntagResource", "cloudwatch:ListTagsForResource",
        ]
        Resource = "arn:aws:cloudwatch:eu-west-2:${data.aws_caller_identity.current.account_id}:alarm:syncify-*"
      },

      # --- SNS ---
      {
        Sid    = "SNS"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic", "sns:DeleteTopic",
          "sns:GetTopicAttributes", "sns:SetTopicAttributes",
          "sns:TagResource", "sns:UntagResource", "sns:ListTagsForResource",
        ]
        Resource = "arn:aws:sns:eu-west-2:${data.aws_caller_identity.current.account_id}:syncify-*"
      },

      # --- CloudWatch Logs (Lambda log groups) ---
      {
        Sid    = "Logs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:DescribeLogGroups",
          "logs:PutRetentionPolicy", "logs:TagResource", "logs:ListTagsForResource",
        ]
        Resource = "arn:aws:logs:eu-west-2:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/syncify-*"
      },

    ]
  })
}

output "deploy_role_arn" {
  value = aws_iam_role.deploy.arn
}
