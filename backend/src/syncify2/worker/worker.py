import posthog

from syncify2.common import spotify, db, scheduling


def run_for_user(user_id: str, request_id: str | None = None):
    if request_id:
        request = db.get_request(user_id, request_id)
        if not request or request.completed:
            return
        _sync(user_id, request, client=None)
    else:
        try:
            with db.sync_slot(user_id):
                _scheduled_sync(user_id)
        except db.SyncSlotTakenError:
            return


def _scheduled_sync(user_id: str):
    client = spotify.get_client(user_id)
    if client is None:
        scheduling.delete_user_schedule(user_id)
        return
    count = spotify.get_liked_count(client)
    if count == 0:
        return
    request = db.create_request(user_id, count)
    _sync(user_id, request, client=client)


def _sync(user_id: str, request: db.SyncRequest, client):
    if client is None:
        client = spotify.get_client(user_id)
    if client is None:
        scheduling.delete_user_schedule(user_id)
        db.complete_request(user_id, request.id)
        return

    count = spotify.get_liked_count(client)
    if count != request.song_count:
        db.update_request_song_count(user_id, request.id, count)

    if count == 0:
        db.complete_request(user_id, request.id)
        return

    print(f"Starting request {request.id} with {count} songs for {user_id}")
    for progress in spotify.sync(client):
        db.update_request_progress(user_id, request.id, progress / (count * 2))

    db.complete_request(user_id, request.id)
    posthog.capture(
        "sync_complete",
        distinct_id=user_id,
        properties={"song_count": count, "id": request.id},
    )
    print(f"Sync request {request.id} complete for {user_id}; {count} songs")
