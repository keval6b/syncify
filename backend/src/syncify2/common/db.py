import uuid
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
    _users_table.delete_item(Key={"userId": user_id})
    _delete_all_requests(user_id)


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
    )


def create_request(user_id: str, song_count: int) -> SyncRequest:
    request_id = str(uuid.uuid4())
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
    )
    items = resp.get("Items", [])
    if not items:
        return None
    items.sort(key=lambda x: x.get("createdAt", ""))
    return _item_to_request(items[0])


def get_recent_requests(user_id: str, limit: int = 10) -> list[SyncRequest]:
    resp = _requests_table.query(
        IndexName="byCreatedAt",
        KeyConditionExpression="userId = :uid",
        ExpressionAttributeValues={":uid": user_id},
        ScanIndexForward=False,
        Limit=limit,
    )
    return [_item_to_request(i) for i in resp.get("Items", [])]


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
    _set_status(user_id, request_id, "failed")


def update_request_song_count(user_id: str, request_id: str, song_count: int):
    _requests_table.update_item(
        Key={"userId": user_id, "requestId": request_id},
        UpdateExpression="SET songCount = :c",
        ExpressionAttributeValues={":c": song_count},
    )


_LOCK_SK = "#lock"


class SyncSlotTakenError(Exception):
    pass


@contextmanager
def sync_slot(user_id: str):
    """Atomically claim the sync slot for the duration of the block.
    Raises SyncSlotTakenError if already claimed.
    TTL is 20 min so a crashed Lambda auto-releases within one slot window."""
    expiry = int((datetime.now(timezone.utc) + timedelta(minutes=20)).timestamp())
    try:
        _requests_table.put_item(
            Item={"userId": user_id, "requestId": _LOCK_SK, "expiresAt": expiry},
            ConditionExpression="attribute_not_exists(requestId)",
        )
    except _requests_table.meta.client.exceptions.ConditionalCheckFailedException:
        raise SyncSlotTakenError
    try:
        yield
    finally:
        _requests_table.delete_item(Key={"userId": user_id, "requestId": _LOCK_SK})


def complete_request(user_id: str, request_id: str):
    _requests_table.update_item(
        Key={"userId": user_id, "requestId": request_id},
        UpdateExpression="SET completedAt = :t, #s = :v",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":t": _now(), ":v": "completed"},
    )


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
