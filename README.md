# PacerPro – Platform Engineer Coding Test

> **Candidate:** Rishabh Nama
> **Role:** Platform Engineer – Cloud Infrastructure & Reliability
> **Email:** rishabhn@terpmail.umd.edu
> **LinkedIn:** linkedin.com/in/rishabhnama
> **GitHub:** github.com/rishabhnama
> **Video Recordings while working:** https://drive.google.com/drive/folders/1Xgb1mV5YolSPuQAS7WQgcJgfHIyU9oP2?usp=sharing

---

## Overview

This solution builds a monitoring and auto-remediation pipeline for a web application experiencing intermittent performance issues. When the `/api/data` endpoint responds slowly, the system detects it automatically, remediates the affected EC2 instance, and notifies the on-call team — with no manual intervention required.

### Architecture

```
Sumo Logic (detects slow requests)
        ↓
SNS Topic (alert notification hub)
        ↓
AWS Lambda (remediates EC2 + sends notification)
        ↓
EC2 Instance (rebooted or started)
        +
CloudWatch Logs (full audit trail)
```

---

## Repository Structure

```
.
├── pacerpro-lambda/
│   └── lambda.py                 # Part 2 – Python Lambda handler
├── sumo-logic/
│   └── sumo-logic-query.txt      # Part 1 – Sumo Logic query
├── terraform/
│   ├── main.tf                   # Part 3 – All AWS resources
│   ├── variables.tf              # Input variables
│   └── outputs.tf                # Resource outputs
├── .gitattributes
├── .gitignore
└── README.md
```

---

## Part 1 – Sumo Logic Query & Alert

**File:** `sumo-logic/sumo-logic-query.txt`

### Query

```
_source="production/app"
| json field=_raw "path" as path
| json field=_raw "response_time" as response_time
| json field=_raw "status" as status
| where (path = "/api/data")
| where num(response_time) > 3
| count as slow_requests
```

### How It Works

The query targets the `production/app` source — the name assigned to the HTTP Source collector during Sumo Logic setup. It parses structured JSON log fields from each raw log line and filters to requests on `/api/data` where response time exceeds 3 seconds. The `num()` cast is critical — Sumo Logic parses JSON values as strings by default, so without this cast the comparison would be lexicographic rather than numeric and produce incorrect results. The `count` operator collapses matching rows into a single number for the alert threshold to evaluate against.

### Alert Configuration

| Setting | Value |
|---|---|
| Monitor type | Logs |
| Evaluation window | Rolling 10 minutes |
| Trigger condition | Count > 5 |
| Severity | Critical |
| Notification | SNS topic → Lambda |

A **rolling** window is used rather than a fixed window. Fixed windows have a boundary blind spot — if 3 slow requests occur at 9:59 and 3 more at 10:01, a fixed window misses the spike entirely. A rolling window catches it.

### Testing the Query

Synthetic log lines are sent to Sumo Logic via the HTTP Source API to validate filter logic:

```bash
# Slow request – should appear in results
curl -X POST "https://endpoint4.collection.sumologic.com/receiver/v1/http/YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"path\": \"/api/data\", \"response_time\": 4.2, \"status\": 200, \"method\": \"GET\"}"

# Fast request – should NOT appear (response_time under threshold)
curl -X POST "https://endpoint4.collection.sumologic.com/receiver/v1/http/YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"path\": \"/api/data\", \"response_time\": 1.1, \"status\": 200, \"method\": \"GET\"}"

# Wrong path – should NOT appear
curl -X POST "https://endpoint4.collection.sumologic.com/receiver/v1/http/YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"path\": \"/api/other\", \"response_time\": 9.9, \"status\": 200, \"method\": \"GET\"}"
```

Negative test cases confirm the filter logic is correct — not just that the query runs without errors.

### Assumptions

- Application emits structured JSON logs with `path`, `response_time`, `status`, and `method` fields
- `response_time` is in seconds. If logged in milliseconds the threshold changes to `> 3000`
- Sumo Logic sends alert notifications to SNS via webhook, which invokes the Lambda

---

## Part 2 – AWS Lambda Function

**File:** `pacerpro-lambda/lambda.py`

### What It Does

The Lambda function is triggered by an SNS message published by the Sumo Logic alert. It:

1. Parses the incoming SNS event to extract alert context
2. Describes the target EC2 instance to check its current state
3. Reboots the instance if running, starts it if stopped, skips gracefully for any other state
4. Logs every step to CloudWatch Logs
5. Publishes a success or failure notification to the SNS topic

### Key Design Decisions

**State check before action**
The function checks the instance state before acting. Calling `reboot_instances` on a stopped instance throws an error. By checking state first the function handles every scenario safely without crashing.

**Three remediation branches**
- `running` → reboot
- `stopped` or `stopping` → start
- anything else (pending, terminating) → skip with a log entry rather than potentially making things worse

**Re-raise on failure**
The except block publishes a failure notification then re-raises the exception. This is intentional — re-raising causes Lambda to mark the invocation as failed, which preserves retry semantics and enables a Dead Letter Queue if configured later. Silent failures are more dangerous than loud ones.

**Environment variables for configuration**
`EC2_INSTANCE_ID` and `SNS_TOPIC_ARN` are read from environment variables — never hardcoded. Terraform populates these automatically from its own resource outputs at deploy time.

### Deployment

Deployed via Terraform (see Part 3). For manual deployment:

```bash
zip lambda.zip lambda.py

aws lambda create-function \
  --function-name pacer-remediation \
  --runtime python3.10 \
  --role arn:aws:iam::ACCOUNT_ID:role/pacer-lambda-exec-role \
  --handler lambda.lambda_handler \
  --zip-file fileb://lambda.zip \
  --environment "Variables={EC2_INSTANCE_ID=i-xxx,SNS_TOPIC_ARN=arn:aws:sns:us-east-1:ACCOUNT:pacer-alerts}" \
  --timeout 30
```

Note: timeout must be set to at least 30 seconds. The default 3 second timeout is insufficient for real AWS API calls to EC2 and SNS.

### Testing

```bash
aws lambda invoke \
  --function-name pacer-remediation \
  --payload '{"Records":[{"Sns":{"Message":"{\"alertName\":\"High Response Time - /api/data\"}"}}]}' \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json
```

Expected response:
```json
{
  "statusCode": 200,
  "body": "{\"instance_id\": \"i-0xxx\", \"action\": \"rebooted\", \"timestamp\": \"2026-03-28T...\"}"
}
```

Verify CloudWatch logs:
```bash
aws logs tail /aws/lambda/pacer-remediation --follow
```

---

## Part 3 – Terraform IaC

**Files:** `terraform/`

### Resources Provisioned

| Resource | Name | Notes |
|---|---|---|
| `aws_instance` | `pacer-webapp` | AL2023, t2.micro, IMDSv2 enforced, encrypted root volume |
| `aws_security_group` | `pacer-webapp-sg` | HTTPS inbound only, no SSH |
| `aws_sns_topic` | `pacer-alerts` | Standard topic, alert and notification hub |
| `aws_sns_topic_subscription` | email | Optional, controlled by `alert_email` variable |
| `aws_lambda_function` | `pacer-remediation` | Python 3.10, 30s timeout, handler `lambda.lambda_handler` |
| `aws_cloudwatch_log_group` | `/aws/lambda/pacer-remediation` | 14-day retention |
| `aws_iam_role` | `pacer-ec2-ssm-role` | SSM access only |
| `aws_iam_role` | `pacer-lambda-exec-role` | Least privilege, scoped to specific resources |
| `aws_lambda_permission` | `AllowSNSInvoke` | Allows SNS to trigger Lambda |
| `aws_sns_topic_subscription` | lambda | Wires SNS → Lambda |

### Least Privilege IAM (Bonus)

The Lambda execution role has four scoped statements:

**EC2 Describe — `resources = ["*"]`**
`DescribeInstances` does not support resource-level restrictions — this is an AWS limitation, not a design choice. Wildcard is unavoidable here.

**EC2 Remediate — `resources = [aws_instance.webapp.arn]`**
`RebootInstances` and `StartInstances` do support resource-level restrictions. This Lambda can only reboot this one specific instance. If the function were compromised it cannot affect any other instance in the account.

**SNS Publish — scoped to single topic ARN**
Can only publish to `pacer-alerts`. Cannot create topics or publish elsewhere.

**CloudWatch Logs — scoped to exact log group ARN**
Can only write to `/aws/lambda/pacer-remediation`. Cannot read or write any other log group.

### Security Hardening

**IMDSv2 enforced on EC2**
```hcl
metadata_options {
  http_endpoint = "enabled"
  http_tokens   = "required"
}
```
IMDSv1 is vulnerable to SSRF attacks where an attacker tricks the server into requesting the metadata endpoint and stealing IAM credentials. IMDSv2 requires a session token handshake which blocks this attack vector entirely.

**No SSH key, no public IP**
The EC2 instance has no key pair attached. Shell access is available via AWS SSM Session Manager, which eliminates the SSH attack surface and removes the need for a bastion host.

**Encrypted EBS volume**
`encrypted = true` on the root block device. No cost, no performance impact, protects data at rest.

### Deployment

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### Verification

```bash
# Confirm all resources exist
terraform output

# Invoke Lambda end to end
aws lambda invoke \
  --function-name pacer-remediation \
  --payload '{"Records":[{"Sns":{"Message":"{\"alertName\":\"Terraform verification test\"}"}}]}' \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json

# Tail logs
aws logs tail /aws/lambda/pacer-remediation --follow
```

### Teardown

```bash
terraform destroy
```

---

## Assumptions & Deviations

| Decision | Rationale |
|---|---|
| `_source` used instead of `_sourceCategory` | Source name is assigned during HTTP Source collector setup in Sumo Logic. Verified against actual collector configuration during testing |
| Structured JSON logs assumed | Modern standard for Rails/Node apps. The `num()` operator handles type casting since Sumo Logic parses all JSON values as strings by default |
| SNS as the Sumo Logic → Lambda bridge | Decouples alerting from remediation. Additional subscribers (PagerDuty, Slack) can be added without touching Lambda |
| Rolling alert window | Catches spikes that span fixed window boundaries |
| No SSH on EC2 | SSM Session Manager is the zero-trust alternative. Eliminates key management and bastion host overhead |
| IMDSv2 enforced | Blocks SSRF-based credential theft. Two line change, significant security improvement |
| Lambda re-raises on failure | Preserves retry semantics and enables Dead Letter Queue support |
| 14-day CloudWatch log retention | Log storage costs money. Infinite retention (Lambda default) is rarely appropriate |
| `terraform.tfvars` excluded from repo | Sensitive environment-specific values never committed to version control |
