import boto3
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _parse_trigger_event(event):
    records = event.get("Records", [])
    if not records:
        return {"source": "unknown", "detail": str(event)}

    raw_message = records[0].get("Sns", {}).get("Message", "{}")
    try:
        payload = json.loads(raw_message)
    except json.JSONDecodeError:
        payload = {"raw": raw_message}

    return {
        "source": payload.get("alertName", "Sumo Logic Alert"),
        "detail": payload,
    }


def _remediate_instance(ec2_client, instance_id):
    describe = ec2_client.describe_instances(InstanceIds=[instance_id])
    reservations = describe.get("Reservations", [])
    if not reservations:
        raise ValueError(f"Instance {instance_id} not found.")

    state = reservations[0]["Instances"][0]["State"]["Name"]
    logger.info("Instance %s current state: %s", instance_id, state)

    if state == "running":
        ec2_client.reboot_instances(InstanceIds=[instance_id])
        action = "rebooted"
    elif state in ("stopped", "stopping"):
        ec2_client.start_instances(InstanceIds=[instance_id])
        action = "started"
    else:
        action = f"skipped (state={state})"

    logger.info("Action taken on %s: %s", instance_id, action)
    return action


def lambda_handler(event, context):
    instance_id = os.environ["EC2_INSTANCE_ID"]
    sns_topic_arn = os.environ["SNS_TOPIC_ARN"]
    timestamp = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Lambda invoked | request_id=%s | instance=%s | ts=%s",
        context.aws_request_id,
        instance_id,
        timestamp,
    )

    ec2 = boto3.client("ec2")
    sns = boto3.client("sns")

    trigger = _parse_trigger_event(event)
    logger.info("Trigger source: %s", trigger["source"])

    try:
        action = _remediate_instance(ec2, instance_id)

        subject = f"[PacerPro] EC2 Auto-Remediation: {instance_id} {action}"
        body = (
            f"Auto-remediation triggered by: {trigger['source']}\n\n"
            f"Instance ID  : {instance_id}\n"
            f"Action taken : {action}\n"
            f"Timestamp    : {timestamp}\n"
            f"Lambda Req ID: {context.aws_request_id}\n"
        )

        sns.publish(TopicArn=sns_topic_arn, Subject=subject, Message=body)
        logger.info("SNS notification published to %s", sns_topic_arn)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "instance_id": instance_id,
                    "action": action,
                    "timestamp": timestamp,
                }
            ),
        }

    except Exception as exc:
        error_msg = f"Remediation failed for {instance_id}: {exc}"
        logger.error(error_msg, exc_info=True)

        try:
            sns.publish(
                TopicArn=sns_topic_arn,
                Subject=f"[PacerPro] REMEDIATION FAILED: {instance_id}",
                Message=error_msg,
            )
        except Exception as sns_exc:
            logger.error("Could not publish failure notification: %s", sns_exc)

        raise