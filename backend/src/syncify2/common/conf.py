import os
import secrets

import posthog


def _read(name: str, default: str = None, optional: bool = False) -> str:
    value = os.environ.get(name, default)
    if value == "":
        value = None
    if not optional and not value:
        raise Exception(f"Environment variable {name} is not set")
    return value


def _read_int(name: str, default: int = None, optional: bool = False) -> int:
    return int(_read(name, default=str(default), optional=optional))


def _read_bool(name: str, default: bool = False) -> bool:
    return _read(name, default=str(default), optional=True).lower() == "true"


base_uri = _read("BASE_URI", "http://127.0.0.1:5000").removesuffix("/")

# JWT secret — must be stable across Lambda invocations (set as env var in prod)
jwt_secret = _read("JWT_SECRET", default=secrets.token_hex())

# DynamoDB table names
users_table = _read("USERS_TABLE", "syncify-users")
requests_table = _read("REQUESTS_TABLE", "syncify-sync-requests")

# SQS
sqs_queue_url = _read("SQS_QUEUE_URL", optional=True)
sqs_queue_arn = _read("SQS_QUEUE_ARN", optional=True)

# EventBridge Scheduler executor role
schedule_role_arn = _read("SCHEDULE_ROLE_ARN", optional=True)

# Analytics
posthog.host = _read("POSTHOG_HOST", default="https://eu.i.posthog.com", optional=True)
posthog.api_key = _read("POSTHOG_API_KEY", optional=True)
posthog.debug = _read_bool("POSTHOG_DEBUG", default="127.0.0.1" in base_uri)
