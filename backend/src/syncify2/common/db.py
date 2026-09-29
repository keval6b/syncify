import uuid_utils
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Literal
import boto3
from boto3.dynamodb.conditions import Attr

from syncify2.common import conf

_ddb = boto3.resource("dynamodb")
_users_table = _ddb.Table(conf.users_table)
_requests_table = _ddb.Table(conf.requests_table)


@dataclass
class User:
    id: str
    refresh_token: str


SyncStatus = Literal["pending", "running", "completed", "failed"]


@dataclass
class SyncRequest:
    id: str
    user_id: str
    song_count: int
    status: SyncStatus
    created: str
    completed: str | None
    phase: str | None = None
    execution_arn: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry_thirty_days() -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())


# --- Users ---


def get_user(user_id: str) -> User | None:
    resp = _users_table.get_item(
        Key={"userId": user_id},
        ConsistentRead=True,
    )
    item = resp.get("Item")
    if not item:
        return None
    return User(id=item["userId"], refresh_token=item["refreshToken"])


def put_user(user: User):
    _users_table.put_item(Item={"userId": user.id, "refreshToken": user.refresh_token})


def delete_user(user_id: str):
    _delete_all_requests(user_id)
    _users_table.delete_item(Key={"userId": user_id})


def scan_all_users() -> list[User]:
    results = []
    resp = _users_table.scan()
    for item in resp.get("Items", []):
        results.append(User(id=item["userId"], refresh_token=item["refreshToken"]))
    while "LastEvaluatedKey" in resp:
        resp = _users_table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        for item in resp.get("Items", []):
            results.append(User(id=item["userId"], refresh_token=item["refreshToken"]))
    return results


# --- Sync Requests ---


def _item_to_request(item: dict) -> SyncRequest:
    # Fallback for rows written before the status migration: derive from completedAt.
    status: SyncStatus = item.get("status") or (
        "completed" if item.get("completedAt") else "pending"
    )
    return SyncRequest(
        id=item["requestId"],
        user_id=item["userId"],
        song_count=int(item.get("songCount", 0)),
        status=status,
        created=item.get("createdAt", ""),
        completed=item.get("completedAt"),
        phase=item.get("phase"),
        execution_arn=item.get("executionArn"),
    )


def create_request(user_id: str, song_count: int) -> SyncRequest:
    request_id = str(uuid_utils.uuid7())
    created_at = _now()
    _requests_table.put_item(
        Item={
            "userId": user_id,
            "requestId": request_id,
            "songCount": song_count,
            "status": "pending",
            "createdAt": created_at,
            "expiresAt": _expiry_thirty_days(),
        }
    )
    return SyncRequest(
        id=request_id,
        user_id=user_id,
        song_count=song_count,
        status="pending",
        created=created_at,
        completed=None,
    )


def get_request(user_id: str, request_id: str) -> SyncRequest | None:
    resp = _requests_table.get_item(
        Key={"userId": user_id, "requestId": request_id},
        ConsistentRead=True,
    )
    item = resp.get("Item")
    return _item_to_request(item) if item else None


def get_pending_request(user_id: str) -> SyncRequest | None:
    resp = _requests_table.query(
        KeyConditionExpression="userId = :uid",
        FilterExpression=Attr("completedAt").not_exists(),
        ExpressionAttributeValues={":uid": user_id},
        ConsistentRead=True,
        ScanIndexForward=True,
    )
    items = [i for i in resp.get("Items", []) if i["requestId"] != _LOCK_SK]
    return _item_to_request(items[0]) if items else None


def get_recent_requests(user_id: str, limit: int = 10) -> list[SyncRequest]:
    resp = _requests_table.query(
        KeyConditionExpression="userId = :uid",
        ExpressionAttributeValues={":uid": user_id},
        ScanIndexForward=False,
    )
    items = [i for i in resp.get("Items", []) if i["requestId"] != _LOCK_SK]
    return [_item_to_request(i) for i in items[:limit]]


def _set_status(user_id: str, request_id: str, status: SyncStatus):
    # `status` is a DynamoDB reserved word, so it's aliased via ExpressionAttributeNames.
    _requests_table.update_item(
        Key={"userId": user_id, "requestId": request_id},
        UpdateExpression="SET #s = :v",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":v": status},
    )


def mark_request_running(user_id: str, request_id: str):
    _set_status(user_id, request_id, "running")


def mark_request_failed(user_id: str, request_id: str):
    _update_existing(
        user_id,
        request_id,
        "SET #s = :v, completedAt = :t",
        {
            ":v": "failed",
            ":t": _now(),
            ":pending": "pending",
            ":running": "running",
        },
        names={"#s": "status"},
        condition="attribute_exists(requestId) AND (#s = :pending OR #s = :running)",
    )
    release_sync_slot(user_id)


def update_request_song_count(user_id: str, request_id: str, song_count: int):
    _requests_table.update_item(
        Key={"userId": user_id, "requestId": request_id},
        UpdateExpression="SET songCount = :c",
        ExpressionAttributeValues={":c": song_count},
    )


_LOCK_SK = "#lock"


class SyncSlotTakenError(Exception):
    pass


# Held until the durable execution finishes. DynamoDB TTL is the backstop if
# the execution is killed without releasing the slot.
_LOCK_TTL = timedelta(hours=6)


def claim_sync_slot(user_id: str):
    """Claim the per-user sync slot. Raises SyncSlotTakenError if it is held."""
    now = int(datetime.now(timezone.utc).timestamp())
    expiry = now + int(_LOCK_TTL.total_seconds())
    try:
        _requests_table.put_item(
            Item={"userId": user_id, "requestId": _LOCK_SK, "expiresAt": expiry},
            ConditionExpression="attribute_not_exists(requestId) OR expiresAt < :now",
            ExpressionAttributeValues={":now": now},
        )
    except _requests_table.meta.client.exceptions.ConditionalCheckFailedException:
        raise SyncSlotTakenError


def release_sync_slot(user_id: str):
    _requests_table.delete_item(Key={"userId": user_id, "requestId": _LOCK_SK})


@contextmanager
def sync_slot(user_id: str):
    """Claim the sync slot for the duration of the block.

    The enqueue and worker paths hold the slot themselves and release it when
    the durable execution completes. This wrapper is for short critical sections.
    """
    claim_sync_slot(user_id)
    try:
        yield
    finally:
        release_sync_slot(user_id)


def _update_existing(
    user_id: str,
    request_id: str,
    expression: str,
    values: dict,
    names: dict | None = None,
    condition: str = "attribute_exists(requestId)",
):
    kwargs = {
        "Key": {"userId": user_id, "requestId": request_id},
        "UpdateExpression": expression,
        "ExpressionAttributeValues": values,
        "ConditionExpression": condition,
    }
    if names:
        kwargs["ExpressionAttributeNames"] = names
    try:
        _requests_table.update_item(**kwargs)
    except _requests_table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True


def set_execution_arn(user_id: str, request_id: str, execution_arn: str):
    _update_existing(
        user_id,
        request_id,
        "SET executionArn = :a",
        {":a": execution_arn},
    )


def save_progress(
    user_id: str,
    request_id: str,
    *,
    phase: str,
    liked_offset: int,
    liked_total: int,
    playlist_index: int,
    playlist_offset: int,
    batch_index: int,
):
    """Persist the small cursor. URI lists live in the slice object, not here."""
    return _update_existing(
        user_id,
        request_id,
        "SET phase = :p, #s = :running, #c = :c",
        {
            ":p": phase,
            ":running": "running",
            ":pending": "pending",
            ":c": {
                "phase": phase,
                "likedOffset": liked_offset,
                "likedTotal": liked_total,
                "playlistIndex": playlist_index,
                "playlistOffset": playlist_offset,
                "batchIndex": batch_index,
            },
        },
        names={"#s": "status", "#c": "cursor"},
        condition="attribute_exists(requestId) AND (#s = :pending OR #s = :running)",
    )


def complete_request(user_id: str, request_id: str):
    updated = _update_existing(
        user_id,
        request_id,
        "SET completedAt = :t, #s = :v",
        {":t": _now(), ":v": "completed", ":pending": "pending", ":running": "running"},
        names={"#s": "status"},
        condition="attribute_exists(requestId) AND (#s = :pending OR #s = :running)",
    )
    if updated:
        release_sync_slot(user_id)


def delete_request(user_id: str, request_id: str):
    _requests_table.delete_item(Key={"userId": user_id, "requestId": request_id})


def _delete_all_requests(user_id: str):
    resp = _requests_table.query(
        KeyConditionExpression="userId = :uid",
        ExpressionAttributeValues={":uid": user_id},
        ProjectionExpression="requestId",
    )
    with _requests_table.batch_writer() as batch:
        for item in resp.get("Items", []):
            batch.delete_item(Key={"userId": user_id, "requestId": item["requestId"]})
        while "LastEvaluatedKey" in resp:
            resp = _requests_table.query(
                KeyConditionExpression="userId = :uid",
                ExpressionAttributeValues={":uid": user_id},
                ProjectionExpression="requestId",
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            for item in resp.get("Items", []):
                batch.delete_item(
                    Key={"userId": user_id, "requestId": item["requestId"]}
                )
