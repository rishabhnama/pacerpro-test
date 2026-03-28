variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name prefix applied to all resource names and tags"
  type        = string
  default     = "pacer"
}

variable "environment" {
  description = "Deployment environment (production | staging | dev)"
  type        = string
  default     = "production"
}

variable "ec2_instance_type" {
  description = "EC2 instance type for the webapp server"
  type        = string
  default     = "t3.micro"
}

variable "vpc_id" {
  description = "VPC ID in which to place the EC2 instance and security group"
  type        = string
  # No default – must be supplied via tfvars or -var flag
}

variable "subnet_id" {
  description = "Private subnet ID for the EC2 instance (no public IP assigned)"
  type        = string
  # No default – must be supplied via tfvars or -var flag
}

variable "alert_email" {
  description = "Optional email address to subscribe to the SNS alert topic"
  type        = string
  default     = ""
  sensitive   = true
}
