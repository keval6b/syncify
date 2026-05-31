import posthog

from syncify2.common import spotify, db, scheduling


def run_for_user(user_id: str, request_id: str | None = None):
    client = None

    if request_id:
        request = db.get_request(user_id, request_id)
        if not request or request.completed:
            return
    else:
        # Scheduler path: claim the slot atomically; skip if already running.
        try:
            db.claim_sync_slot(user_id)
        except db.SyncSlotTakenError:
            return
        client = spotify.get_client(user_id)
        if client is None:
            scheduling.delete_user_schedule(user_id)
            db.release_sync_slot(user_id)
            return
        count = spotify.get_liked_count(client)
        if count == 0:
            db.release_sync_slot(user_id)
            return
        request = db.create_request(user_id, count)

    if client is None:
        client = spotify.get_client(user_id)
    if client is None:
        scheduling.delete_user_schedule(user_id)
        db.complete_request(user_id, request.id)
        db.release_sync_slot(user_id)
        return

    count = spotify.get_liked_count(client)
    if count != request.song_count:
        db.update_request_song_count(user_id, request.id, count)

    if count == 0:
        db.complete_request(user_id, request.id)
        db.release_sync_slot(user_id)
        return

    print(f"Starting request {request.id} with {count} songs for {user_id}")
    for progress in spotify.sync(client):
        db.update_request_progress(user_id, request.id, progress / (count * 2))

    db.complete_request(user_id, request.id)
    db.release_sync_slot(user_id)
    posthog.capture(
        "sync_complete",
        distinct_id=user_id,
        properties={"song_count": count, "id": request.id},
    )
    print(f"Sync request {request.id} complete for {user_id}; {count} songs")
