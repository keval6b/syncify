import datetime

from fastapi import Request, HTTPException
from jose import jwt, JWTError
from starlette import status

from syncify2.common import conf

ALGORITHM = "HS256"
COOKIE_OAUTH = "syncify_oauth"
COOKIE_SESSION = "syncify_session"
_OAUTH_TTL = datetime.timedelta(minutes=5)
_SESSION_TTL = datetime.timedelta(days=30)


def _encode(payload: dict, ttl: datetime.timedelta) -> str:
    data = payload.copy()
    data["exp"] = datetime.datetime.now(datetime.timezone.utc) + ttl
    return jwt.encode(data, conf.jwt_secret, algorithm=ALGORITHM)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, conf.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid or expired session")


def create_oauth_token(state: str, redirect_uri: str) -> str:
    return _encode(
        {"type": "oauth", "state": state, "redirect_uri": redirect_uri}, _OAUTH_TTL
    )


def create_session_token(user_id: str) -> str:
    return _encode({"type": "user", "user_id": user_id}, _SESSION_TTL)


def get_oauth_payload(request: Request) -> tuple[str, str]:
    """Returns (state, redirect_uri)."""
    token = request.cookies.get(COOKIE_OAUTH)
    if not token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No OAuth session")
    payload = _decode(token)
    if payload.get("type") != "oauth":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid session type")
    return payload["state"], payload["redirect_uri"]


def get_user_id(request: Request) -> str:
    token = request.cookies.get(COOKIE_SESSION)
    if not token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authenticated")
    payload = _decode(token)
    if payload.get("type") != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid session type")
    return payload["user_id"]
