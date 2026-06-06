#!/usr/bin/env python3
"""
Re-key sync-request requestIds from UUIDv4 to UUIDv7.

Run BEFORE deploying the infra change that drops the byCreatedAt GSI.

Usage:
    TABLE=stg-sync-requests uv run scripts/migrate_uuidv7.py
    TABLE=prd-sync-requests uv run scripts/migrate_uuidv7.py

Set DRY_RUN=1 to preview without writing.
"""

import os
import sys

import boto3
import uuid_utils

TABLE_NAME = os.environ["TABLE"]
LOCK_SK = "#lock"
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


def _is_uuid7(s: str) -> bool:
    parts = s.split("-")
    return len(parts) == 5 and parts[2].startswith("7")


def main():
    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    print(f"Scanning {TABLE_NAME}...")
    items: list[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))

    print(f"  {len(items)} total items")

    to_migrate = [
        i for i in items
        if i["requestId"] != LOCK_SK and not _is_uuid7(i["requestId"])
    ]
    already_done = len(items) - len(to_migrate) - sum(
        1 for i in items if i["requestId"] == LOCK_SK
    )
    print(f"  {len(to_migrate)} need migration, {already_done} already UUIDv7")

    if not to_migrate:
        print("Nothing to do.")
        return

    # Sort ascending by createdAt so generated UUIDv7s preserve chronological order.
    to_migrate.sort(key=lambda x: x.get("createdAt", ""))

    if DRY_RUN:
        print("DRY RUN - no writes.")
        for item in to_migrate:
            print(f"  {item['userId']} / {item['requestId']} ({item.get('createdAt', '')})")
        return

    migrated = 0
    errors = 0
    for item in to_migrate:
        old_id = item["requestId"]
        new_id = str(uuid_utils.uuid7())
        try:
            # Write new item before deleting old - never lose data on partial failure.
            table.put_item(Item={**item, "requestId": new_id})
            table.delete_item(Key={"userId": item["userId"], "requestId": old_id})
            migrated += 1
            print(f"  [{migrated}/{len(to_migrate)}] {item['userId']}  {old_id} -> {new_id}")
        except Exception as exc:
            errors += 1
            print(f"  ERROR {item['userId']} / {old_id}: {exc}", file=sys.stderr)

    print(f"\nDone. {migrated} migrated, {errors} errors.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
