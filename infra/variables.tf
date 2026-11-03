variable "aws_region" {
  description = "Region the pipeline is deployed into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix applied to every resource name."
  type        = string
  default     = "erp-integration"
}

variable "environment" {
  description = "Environment name, used in resource names and tags."
  type        = string
  default     = "dev"
}

variable "alert_email" {
  description = "Address that receives load alerts. Leave empty to skip the subscription."
  type        = string
  default     = ""
}

variable "reject_rate_threshold" {
  description = "Share of rejected rows above which a load raises an alert."
  type        = string
  default     = "0.10"

  validation {
    condition     = can(tonumber(var.reject_rate_threshold)) && tonumber(var.reject_rate_threshold) > 0 && tonumber(var.reject_rate_threshold) <= 1
    error_message = "The reject rate threshold must be a number greater than 0 and no more than 1."
  }
}

variable "retention_days" {
  description = "Days before old object versions and summaries expire."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "Days of function logs kept in CloudWatch."
  type        = number
  default     = 14
}

variable "enable_point_in_time_recovery" {
  description = "Point in time recovery on the supplier table. Costs money, so off by default."
  type        = bool
  default     = false
}

variable "create_reader_role" {
  description = "Create the read only reviewer role."
  type        = bool
  default     = true
}

variable "force_destroy_bucket" {
  description = "Allow terraform destroy to remove a bucket that still holds files. Useful while learning, unsafe in production."
  type        = bool
  default     = true
}
