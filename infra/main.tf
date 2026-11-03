terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# ---------------------------------------------------------------------------
# Landing bucket
#
# One bucket with three prefixes: inbound/ for files from the source systems,
# rejects/ for the per file reject reports, summaries/ for the load summaries.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "landing" {
  bucket        = "${local.name_prefix}-landing"
  force_destroy = var.force_destroy_bucket
}

# Public access is blocked outright. Supplier master data is not public.
resource "aws_s3_bucket_public_access_block" "landing" {
  bucket = aws_s3_bucket.landing.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning keeps the original file when a corrected extract is re-uploaded
# under the same name, which happens constantly during a migration.
resource "aws_s3_bucket_versioning" "landing" {
  bucket = aws_s3_bucket.landing.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Old versions and reports expire so the bucket stays inside the free tier.
resource "aws_s3_bucket_lifecycle_configuration" "landing" {
  bucket     = aws_s3_bucket.landing.id
  depends_on = [aws_s3_bucket_versioning.landing]

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.retention_days
    }
  }

  rule {
    id     = "expire-reports"
    status = "Enabled"

    filter {
      prefix = "summaries/"
    }

    expiration {
      days = var.retention_days
    }
  }
}

# ---------------------------------------------------------------------------
# Supplier table
#
# On demand billing keeps this inside the always free DynamoDB allowance
# rather than the twelve month trial.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "suppliers" {
  name         = "${local.name_prefix}-suppliers"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "supplier_key"

  attribute {
    name = "supplier_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }
}

# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-load-alerts"
}

resource "aws_sns_topic_subscription" "alert_email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------------------------------------------------------------------------
# Ingestion function
# ---------------------------------------------------------------------------

data "archive_file" "ingest" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/../build/ingest.zip"
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.name_prefix}-ingest"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "ingest" {
  function_name = "${local.name_prefix}-ingest"
  role          = aws_iam_role.ingest.arn
  handler       = "ingest.handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 256

  filename         = data.archive_file.ingest.output_path
  source_code_hash = data.archive_file.ingest.output_base64sha256

  environment {
    variables = {
      SUPPLIER_TABLE_NAME    = aws_dynamodb_table.suppliers.name
      ALERT_TOPIC_ARN        = aws_sns_topic.alerts.arn
      REJECT_RATE_THRESHOLD  = var.reject_rate_threshold
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingest]
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.landing.arn
}

# Only inbound/ triggers the function. Without the prefix filter the reject
# and summary files the function writes would trigger it again.
resource "aws_s3_bucket_notification" "inbound" {
  bucket = aws_s3_bucket.landing.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "inbound/"
    filter_suffix       = ".csv"
  }

  depends_on = [aws_lambda_permission.allow_s3]
}

# ---------------------------------------------------------------------------
# Operational alarm
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ingest_errors" {
  alarm_name          = "${local.name_prefix}-ingest-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "The supplier ingestion function failed at least once in five minutes."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.ingest.function_name
  }
}
