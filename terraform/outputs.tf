output "ec2_instance_id" {
  description = "ID of the webapp EC2 instance"
  value       = aws_instance.webapp.id
}

output "sns_topic_arn" {
  description = "ARN of the SNS alert topic"
  value       = aws_sns_topic.pacer_alerts.arn
}

output "lambda_function_name" {
  description = "Name of the remediation Lambda function"
  value       = aws_lambda_function.remediation.function_name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for Lambda execution logs"
  value       = aws_cloudwatch_log_group.lambda.name
}