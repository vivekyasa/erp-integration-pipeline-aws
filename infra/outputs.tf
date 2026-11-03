output "landing_bucket" {
  description = "Bucket that receives inbound supplier files."
  value       = aws_s3_bucket.landing.id
}

output "inbound_prefix" {
  description = "Where to upload a file to trigger a load."
  value       = "s3://${aws_s3_bucket.landing.id}/inbound/"
}

output "supplier_table" {
  description = "Table holding the loaded supplier records."
  value       = aws_dynamodb_table.suppliers.name
}

output "ingest_function" {
  description = "Name of the ingestion function."
  value       = aws_lambda_function.ingest.function_name
}

output "alert_topic_arn" {
  description = "Topic that load alerts are published to."
  value       = aws_sns_topic.alerts.arn
}

output "log_group" {
  description = "CloudWatch log group for the ingestion function."
  value       = aws_cloudwatch_log_group.ingest.name
}
