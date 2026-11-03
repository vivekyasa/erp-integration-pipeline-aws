# Least privilege roles for the pipeline.
#
# The ingestion function is granted exactly what it needs and nothing more:
# read from inbound/, write only to rejects/ and summaries/, write to the
# supplier table, and publish to the one alert topic. It cannot delete
# objects, cannot read the whole bucket, and cannot touch any other table.

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest" {
  name               = "${local.name_prefix}-ingest-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "ingest" {
  # Read inbound files only. The function has no reason to read the reject
  # reports it writes, so the prefix is scoped rather than bucket wide.
  statement {
    sid       = "ReadInboundFiles"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.landing.arn}/inbound/*"]
  }

  # Write reports back, without any delete permission.
  statement {
    sid     = "WriteReports"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.landing.arn}/rejects/*",
      "${aws_s3_bucket.landing.arn}/summaries/*",
    ]
  }

  # Upsert supplier records. No scan or delete: the function only writes.
  statement {
    sid    = "WriteSupplierRecords"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:BatchWriteItem",
    ]
    resources = [aws_dynamodb_table.suppliers.arn]
  }

  statement {
    sid       = "PublishLoadAlerts"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.ingest.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ingest" {
  name   = "${local.name_prefix}-ingest-policy"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest.json
}

# ---------------------------------------------------------------------------
# Read only role for anyone reviewing the loaded data.
#
# This mirrors the owner and reader split used on the database side: the
# people checking a load can read the records and the reports, and cannot
# change either.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "reader_assume_role" {
  count = var.create_reader_role ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "reader" {
  count              = var.create_reader_role ? 1 : 0
  name               = "${local.name_prefix}-reader-role"
  assume_role_policy = data.aws_iam_policy_document.reader_assume_role[0].json
}

data "aws_iam_policy_document" "reader" {
  count = var.create_reader_role ? 1 : 0

  statement {
    sid    = "ReadReportsAndFiles"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.landing.arn,
      "${aws_s3_bucket.landing.arn}/*",
    ]
  }

  statement {
    sid    = "ReadSupplierRecords"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.suppliers.arn]
  }
}

resource "aws_iam_role_policy" "reader" {
  count  = var.create_reader_role ? 1 : 0
  name   = "${local.name_prefix}-reader-policy"
  role   = aws_iam_role.reader[0].id
  policy = data.aws_iam_policy_document.reader[0].json
}
