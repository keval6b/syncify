import json

import boto3
from botocore.exceptions import ClientError

from syncify2.common import conf, db, scheduling, spotify

_lambda = boto3.client("lambda")


def handler(event, context):
    """SQS entrypoint. Starts one named durable execution and returns.

    The queue mapping cannot host the sync itself: a durable execution started
    by an event source mapping is capped at 15 minutes, and a retry would
    start a second execution. Invoking by request id makes that retry attach
    to the one already running.
    """
    failures = []
    for record in event["Records"]:
        try:
            body = json.loads(record["body"])
            _dispatch(body)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "dispatch_failed",
                        "message_id": record.get("messageId"),
                        "error": type(exc).__name__,
                        "detail": str(exc),
                    }
                )
            )
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _dispatch(body: dict):
    user_id = body["user_id"]
    request_id = body.get("request_id")
    if request_id is None:
        request_id = _start_scheduled(user_id)
        if request_id is None:
            return
    else:
        request = db.get_request(user_id, request_id)
        if request is None or request.status in ("completed", "failed") or request.completed:
            print(
                json.dumps(
                    {
                        "event": "request_not_run",
                        "user_id": user_id,
                        "request_id": request_id,
                        "status": None if request is None else request.status,
                    }
                )
            )
            return
    _start_execution(user_id, request_id)


def _start_scheduled(user_id: str) -> str | None:
    client = spotify.get_client(user_id)
    if client is None:
        scheduling.delete_user_schedule(user_id)
        return None
    count = spotify.get_liked_count(client)
    if count == 0:
        return None
    try:
        db.claim_sync_slot(user_id)
    except db.SyncSlotTakenError:
        # A retry of this message, or a sync already in progress. Reattach to
        # that request instead of dropping the schedule tick.
        existing = db.get_pending_request(user_id)
        if existing is None or existing.status in ("completed", "failed"):
            return None
        return existing.id
    try:
        request = db.create_request(user_id, count)
    except Exception:
        db.release_sync_slot(user_id)
        raise
    return request.id


def _start_execution(user_id: str, request_id: str):
    payload = {"user_id": user_id, "request_id": request_id}
    try:
        resp = _lambda.invoke(
            FunctionName=conf.durable_function_name,
            InvocationType="Event",
            DurableExecutionName=request_id,
            Payload=json.dumps(payload).encode(),
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "DurableExecutionAlreadyStartedException":
            return
        raise
    arn = resp.get("DurableExecutionArn")
    if arn:
        db.set_execution_arn(user_id, request_id, arn)
