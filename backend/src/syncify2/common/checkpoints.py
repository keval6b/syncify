"""One JSON object per sync slice. The object holds the URI lists; the request
row holds only the cursor."""

import json

import boto3
from botocore.exceptions import ClientError

from syncify2.common import conf

_s3 = boto3.client("s3")


def _key(user_id: str, request_id: str, slice_index: int) -> str:
    return f"{user_id}/{request_id}/slice-{slice_index}.json"


def load_slice(user_id: str, request_id: str, slice_index: int) -> dict | None:
    try:
        resp = _s3.get_object(
            Bucket=conf.checkpoint_bucket,
            Key=_key(user_id, request_id, slice_index),
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(resp["Body"].read())


def save_slice(user_id: str, request_id: str, slice_index: int, state: dict):
    _s3.put_object(
        Bucket=conf.checkpoint_bucket,
        Key=_key(user_id, request_id, slice_index),
        Body=json.dumps(state).encode(),
        ContentType="application/json",
    )
