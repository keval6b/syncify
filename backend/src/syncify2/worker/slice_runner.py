"""One time-boxed slice of a sync.

The durable function calls this up to four times. URI lists are written to the
slice object. The request row only stores the cursor the dashboard reads.
"""

import copy
import time
from dataclasses import dataclass

import posthog

from syncify2.common import checkpoints, db, scheduling, spotify

_SLICE_SECONDS = 12 * 60
_LIKED_PAGE = 50
_PAGES_BETWEEN_CHECKPOINTS = 4

_PHASE_FETCH_LIKED = "fetch_liked"
_PHASE_FETCH_PLAYLISTS = "fetch_playlists"
_PHASE_PLAN = "plan"
_PHASE_APPLY = "apply"
_PHASE_DONE = "done"


@dataclass
class SliceResult:
    done: bool
    wait_seconds: int
    cursor_moved: bool

    def as_dict(self) -> dict:
        return {
            "done": self.done,
            "wait_seconds": self.wait_seconds,
            "cursor_moved": self.cursor_moved,
        }


def _empty_state() -> dict:
    return {
        "phase": _PHASE_FETCH_LIKED,
        "likedOffset": 0,
        "likedTotal": 0,
        "liked": [],
        "playlists": [],
        "playlistIndex": 0,
        "playlistOffset": 0,
        "batchIndex": 0,
        "batches": [],
    }


def _cursor_key(state: dict):
    return (
        state["phase"],
        state["likedOffset"],
        state["playlistIndex"],
        state["playlistOffset"],
        state["batchIndex"],
    )


def _load_state(user_id: str, request_id: str, slice_index: int) -> dict:
    current = checkpoints.load_slice(user_id, request_id, slice_index)
    if current is not None:
        return copy.deepcopy(current)
    if slice_index > 0:
        previous = checkpoints.load_slice(user_id, request_id, slice_index - 1)
        if previous is not None:
            return copy.deepcopy(previous)
    return _empty_state()


def _persist(user_id: str, request_id: str, slice_index: int, state: dict) -> bool:
    checkpoints.save_slice(user_id, request_id, slice_index, state)
    return db.save_progress(
        user_id,
        request_id,
        phase=state["phase"],
        liked_offset=state["likedOffset"],
        liked_total=state["likedTotal"],
        playlist_index=state["playlistIndex"],
        playlist_offset=state["playlistOffset"],
        batch_index=state["batchIndex"],
    )


def _liked_page(client, offset: int):
    page = client.current_user_saved_tracks(limit=_LIKED_PAGE, offset=offset)
    uris = [item["track"]["uri"] for item in page["items"] if item.get("track")]
    raw = len(page["items"])
    total = int(page["total"])
    return uris, total, raw, raw > 0 and offset + raw < total


def _playlist_page(client, playlist_id: str, offset: int):
    page = client.playlist_items(playlist_id, limit=spotify._API_PAGE, offset=offset)
    uris = [item["track"]["uri"] for item in page["items"] if item.get("track")]
    raw = len(page["items"])
    total = int(page.get("total", offset + raw))
    return uris, raw, raw > 0 and offset + raw < total


def _discover_playlists(client, state: dict):
    found = []
    for playlist in spotify._all_playlists(client):
        name = playlist.get("name") or ""
        if name.startswith("Syncify ") and playlist.get("id"):
            found.append(
                {"name": name, "id": playlist["id"], "uris": [], "complete": False}
            )
    state["playlists"] = found
    state["playlistIndex"] = 0
    state["playlistOffset"] = 0


def _build_plan(client, state: dict):
    liked = state["liked"]
    chunks = [
        liked[i : i + spotify._PLAYLIST_SIZE]
        for i in range(0, len(liked), spotify._PLAYLIST_SIZE)
    ]
    existing = {playlist["name"]: playlist for playlist in state["playlists"]}
    batches = []
    total = len(chunks)
    for idx, target in enumerate(chunks, start=1):
        name = f"Syncify {idx}/{total}"
        if name in existing:
            playlist_id = existing[name]["id"]
            current = existing[name]["uris"]
        else:
            playlist_id = spotify.get_playlist_id(client, name)
            current = []
        to_remove, inserts = spotify._diff(current, target)
        for batch in spotify._batches(to_remove, spotify._API_PAGE):
            batches.append(
                {
                    "op": "remove",
                    "playlistId": playlist_id,
                    "position": 0,
                    "uris": list(batch),
                }
            )
        for position, items in inserts:
            pos = position
            for batch in spotify._batches(items, spotify._API_PAGE):
                batches.append(
                    {
                        "op": "insert",
                        "playlistId": playlist_id,
                        "position": pos,
                        "uris": list(batch),
                    }
                )
                pos += len(batch)
    state["batches"] = batches
    state["batchIndex"] = 0
    state["phase"] = _PHASE_APPLY if batches else _PHASE_DONE


def _apply_batch(client, batch: dict):
    if batch["op"] == "remove":
        client.playlist_remove_all_occurrences_of_items(
            batch["playlistId"], batch["uris"]
        )
        return
    spotify.add_items_idempotent(
        client, batch["playlistId"], batch["uris"], batch["position"]
    )


def _finish(user_id: str, request_id: str, state: dict, slice_index: int, started):
    state["phase"] = _PHASE_DONE
    if not _persist(user_id, request_id, slice_index, state):
        return SliceResult(done=True, wait_seconds=0, cursor_moved=True)
    db.complete_request(user_id, request_id)
    posthog.capture(
        "sync_complete",
        distinct_id=user_id,
        properties={"song_count": state["likedTotal"], "id": request_id},
    )
    print(
        f"Sync request {request_id} complete for {user_id}; {state['likedTotal']} songs"
    )
    return SliceResult(
        done=True, wait_seconds=0, cursor_moved=_cursor_key(state) != started
    )


def run_slice(
    user_id: str,
    request_id: str,
    slice_index: int,
    *,
    clock=time.monotonic,
    deadline: float | None = None,
) -> SliceResult:
    """Run until the slice budget, a long rate limit, or the sync finishes."""
    request = db.get_request(user_id, request_id)
    if request is None:
        print(f"request {request_id} for {user_id} is gone; not starting another sync")
        db.release_sync_slot(user_id)
        return SliceResult(done=True, wait_seconds=0, cursor_moved=True)
    if request.status in ("failed", "completed") or request.completed:
        return SliceResult(done=True, wait_seconds=0, cursor_moved=True)

    if deadline is None:
        deadline = clock() + _SLICE_SECONDS

    state = _load_state(user_id, request_id, slice_index)
    started = _cursor_key(state)
    pages_since_checkpoint = 0

    stopped = False

    def checkpoint():
        nonlocal pages_since_checkpoint, stopped
        if not _persist(user_id, request_id, slice_index, state):
            stopped = True
        pages_since_checkpoint = 0

    def maybe_checkpoint():
        nonlocal pages_since_checkpoint
        pages_since_checkpoint += 1
        if pages_since_checkpoint >= _PAGES_BETWEEN_CHECKPOINTS:
            checkpoint()

    try:
        client = spotify.get_client(user_id)
        if client is None:
            scheduling.delete_user_schedule(user_id)
            db.complete_request(user_id, request_id)
            return SliceResult(done=True, wait_seconds=0, cursor_moved=True)

        if state["phase"] == _PHASE_FETCH_LIKED and state["likedOffset"] == 0:
            db.mark_request_running(user_id, request_id)
            print(f"Starting request {request_id} for {user_id}")

        while clock() < deadline and state["phase"] != _PHASE_DONE and not stopped:
            if state["phase"] == _PHASE_FETCH_LIKED:
                uris, total, raw, more = _liked_page(client, state["likedOffset"])
                state["likedTotal"] = total
                if total != request.song_count:
                    db.update_request_song_count(user_id, request_id, total)
                    request.song_count = total
                state["liked"].extend(uris)
                state["likedOffset"] += raw
                maybe_checkpoint()
                if not more:
                    state["phase"] = _PHASE_DONE if total == 0 else _PHASE_FETCH_PLAYLISTS
                    checkpoint()
                continue

            if state["phase"] == _PHASE_FETCH_PLAYLISTS:
                if not state.get("playlistsDiscovered"):
                    _discover_playlists(client, state)
                    state["playlistsDiscovered"] = True
                    checkpoint()
                if state["playlistIndex"] >= len(state["playlists"]):
                    state["phase"] = _PHASE_PLAN
                    checkpoint()
                    continue
                playlist = state["playlists"][state["playlistIndex"]]
                uris, raw, more = _playlist_page(
                    client, playlist["id"], state["playlistOffset"]
                )
                playlist["uris"].extend(uris)
                state["playlistOffset"] += raw
                maybe_checkpoint()
                if not more:
                    playlist["complete"] = True
                    state["playlistIndex"] += 1
                    state["playlistOffset"] = 0
                    checkpoint()
                continue

            if state["phase"] == _PHASE_PLAN:
                _build_plan(client, state)
                checkpoint()
                continue

            if state["phase"] == _PHASE_APPLY:
                if state["batchIndex"] >= len(state["batches"]):
                    state["phase"] = _PHASE_DONE
                    continue
                _apply_batch(client, state["batches"][state["batchIndex"]])
                state["batchIndex"] += 1
                maybe_checkpoint()
                continue

            break
    except spotify.SpotifyRateLimited as limited:
        checkpoint()
        return SliceResult(
            done=False,
            wait_seconds=limited.retry_after,
            cursor_moved=_cursor_key(state) != started,
        )

    if stopped:
        return SliceResult(done=True, wait_seconds=0, cursor_moved=True)

    if state["phase"] == _PHASE_DONE:
        return _finish(user_id, request_id, state, slice_index, started)

    checkpoint()
    return SliceResult(
        done=False,
        wait_seconds=0,
        cursor_moved=_cursor_key(state) != started,
    )
