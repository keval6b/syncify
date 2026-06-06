import json

from syncify2.worker import worker


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        user_id = body["user_id"]
        request_id = body.get("request_id")
        receive_count = record.get("attributes", {}).get("ApproximateReceiveCount", "?")
        print(
            json.dumps(
                {
                    "event": "worker_invoked",
                    "user_id": user_id,
                    "request_id": request_id,
                    "receive_count": receive_count,
                    "message_id": record.get("messageId"),
                }
            )
        )
        worker.run_for_user(user_id=user_id, request_id=request_id)
    return {"statusCode": 200}
