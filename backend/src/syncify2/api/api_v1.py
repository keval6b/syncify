import json
import secrets

import boto3
import posthog
import spotipy
from fastapi import Request, HTTPException, APIRouter
from starlette import status
from starlette.responses import Response, RedirectResponse

from syncify2.common import spotify, db, conf
from syncify2.common import scheduling
from syncify2.api import session
from syncify2.api.types import UserResponse

router = APIRouter(prefix="/api/v1", tags=["API v1"])

_sqs = boto3.client("sqs")


def _set_session_cookie(response: Response, token: str, cookie_name: str, max_age: int):
    response.set_cookie(
        key=cookie_name,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age,
    )


def _clear_cookie(response: Response, cookie_name: str):
    response.delete_cookie(key=cookie_name, httponly=True, secure=True, samesite="lax")


@router.get("/auth/login")
def login(request: Request, response: Response, redirect_uri: str) -> str:
    state = secrets.token_urlsafe()
    _set_session_cookie(
        response,
        session.create_oauth_token(state, redirect_uri),
        session.COOKIE_OAUTH,
        300,
    )
    return spotify.make_oauth(redirect_uri).get_authorize_url(state)


@router.get("/auth/callback")
def callback(request: Request):
    state, redirect_uri = session.get_oauth_payload(request)
    if request.query_params.get("state") != state:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid state")

    try:
        token_response = spotify.make_oauth(redirect_uri).get_access_token(
            request.query_params.get("code"), check_cache=False
        )
    except ConnectionError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Failed to complete Spotify authentication. Please retry.",
        )
    if not token_response or "access_token" not in token_response:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Invalid response from Spotify during authentication.",
        )

    client = spotipy.Spotify(auth=token_response["access_token"])
    user = client.current_user()
    user_id = user["id"]

    db.put_user(db.User(id=user_id, refresh_token=token_response["refresh_token"]))
    scheduling.create_user_schedule(user_id)
    posthog.identify(
        user_id,
        properties={"display_name": user.get("display_name")},
    )

    redirect = RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    _clear_cookie(redirect, session.COOKIE_OAUTH)
    _set_session_cookie(
        redirect,
        session.create_session_token(user_id),
        session.COOKIE_SESSION,
        60 * 60 * 24 * 30,
    )
    return redirect


@router.get("/auth/user")
def get_user(request: Request):
    user_id = session.get_user_id(request)
    client = spotify.get_client(user_id)
    if client is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not logged in")
    user = client.me()
    return UserResponse(id=user["id"], display_name=user["display_name"])


@router.get("/auth/logout")
def logout(response: Response):
    _clear_cookie(response, session.COOKIE_SESSION)


@router.post("/auth/delete")
def delete_user(request: Request, response: Response):
    user_id = session.get_user_id(request)
    scheduling.delete_user_schedule(user_id)
    db.delete_user(user_id)
    _clear_cookie(response, session.COOKIE_SESSION)
    posthog.capture("delete_account", distinct_id=user_id)


@router.put("/jobs")
def enqueue(request: Request):
    user_id = session.get_user_id(request)

    client = spotify.get_client(user_id)
    if client is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not logged in")

    count = spotify.get_liked_count(client)
    if count == 0:
        return

    try:
        with db.sync_slot(user_id):
            sync_request = db.create_request(user_id, count)
            _sqs.send_message(
                QueueUrl=conf.sqs_queue_url,
                MessageBody=json.dumps(
                    {"user_id": user_id, "request_id": sync_request.id}
                ),
            )
    except db.SyncSlotTakenError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You already have a pending sync request"
        )
    posthog.capture(
        "enqueued_sync_request",
        distinct_id=user_id,
        properties={"id": sync_request.id},
    )


@router.get("/jobs")
def jobs(request: Request):
    user_id = session.get_user_id(request)
    return db.get_recent_requests(user_id)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, request: Request):
    user_id = session.get_user_id(request)
    sync_request = db.get_request(user_id, job_id)
    if not sync_request or sync_request.status != "pending":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    db.delete_request(user_id, job_id)
    posthog.capture(
        "deleted_sync_request", distinct_id=user_id, properties={"id": job_id}
    )
