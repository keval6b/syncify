import json
import os
import re

import boto3

from syncify2.common import conf

_scheduler = boto3.client("scheduler")

SCHEDULE_GROUP = "syncify-users"


def _schedule_name(user_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)


def create_user_schedule(user_id: str):
    # Delete first so this is idempotent — also resets the 24h window on re-login.
    delete_user_schedule(user_id)
    _scheduler.create_schedule(
        GroupName=SCHEDULE_GROUP,
        Name=_schedule_name(user_id),
        ScheduleExpression="rate(24 hours)",
        FlexibleTimeWindow={"Mode": "FLEXIBLE", "MaximumWindowInMinutes": 60},
        Target={
            "Arn": conf.sqs_queue_arn,
            "RoleArn": conf.schedule_role_arn,
            "Input": json.dumps({"user_id": user_id, "source": "scheduler"}),
        },
        Tags=[
            {"Key": "service", "Value": "syncify"},
            {"Key": "user_id", "Value": user_id},
            {"Key": "environment", "Value": os.environ.get("ENVIRONMENT", "prd")},
        ],
    )


def delete_user_schedule(user_id: str):
    try:
        _scheduler.delete_schedule(
            GroupName=SCHEDULE_GROUP,
            Name=_schedule_name(user_id),
        )
    except _scheduler.exceptions.ResourceNotFoundException:
        pass
