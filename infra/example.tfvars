# Copy to terraform.tfvars and edit before running terraform apply.

aws_region  = "us-east-1"
environment = "dev"

# Address that receives load alerts. AWS sends a confirmation email that you
# must accept before any alert is delivered. Leave empty to skip alerts.
alert_email = ""

# Raise an alert when more than this share of rows in a file is rejected.
reject_rate_threshold = "0.10"
