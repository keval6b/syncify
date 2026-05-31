import json

from syncify2.worker import worker


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        worker.run_for_user(
            user_id=body["user_id"],
            request_id=body.get("request_id"),
        )
    return {"statusCode": 200}
