import bisect
import concurrent.futures
import json
import time

import requests
import spotipy
from requests.adapters import HTTPAdapter
from spotipy import Spotify
from urllib3.util.retry import Retry

from syncify2.common import db

_PLAYLIST_SIZE = 10000  # max tracks Spotify allows in one playlist
_API_PAGE = 100  # max items per add / remove / playlist_items page

# Spotify rate-limits aggressively on large libraries. spotipy retries 429s
# internally and silently, so we instrument the retry path to surface them.
_RETRY_STATUSES = (429, 500, 502, 503, 504)


def _emit_429(retry_after, url):
    """Log a single Spotify 429 and emit it as a CloudWatch metric.

    The `_aws` block is Embedded Metric Format: Lambda parses it from stdout
    and publishes Syncify/Spotify RateLimited429 with no extra IAM or API call.
    """
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "Syncify/Spotify",
                            "Dimensions": [[]],
                            "Metrics": [{"Name": "RateLimited429", "Unit": "Count"}],
                        }
                    ],
                },
                "RateLimited429": 1,
                "event": "spotify_429",
                "retryAfter": retry_after,
                "path": url,
            }
        )
    )


class _LoggingRetry(Retry):
    """spotipy's Retry, but every 429 it would silently retry is recorded."""

    def increment(self, method=None, url=None, response=None, error=None, **kwargs):
        if response is not None and getattr(response, "status", None) == 429:
            retry_after = None
            headers = getattr(response, "headers", None)
            if headers is not None:
                retry_after = headers.get("Retry-After")
            _emit_429(retry_after, url)
        return super().increment(
            method=method, url=url, response=response, error=error, **kwargs
        )


def _build_session() -> requests.Session:
    """A requests session mirroring spotipy's default retry/backoff, with the
    429-logging Retry mounted in place of the stock one."""
    retry = _LoggingRetry(
        total=3,
        connect=None,
        read=False,
        allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE"]),
        status=3,
        backoff_factor=0.3,
        status_forcelist=_RETRY_STATUSES,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_SCOPE = "playlist-read-private,playlist-modify-private,user-library-read,playlist-modify-public"


def make_oauth(redirect_uri: str) -> spotipy.oauth2.SpotifyOAuth:
    return spotipy.oauth2.SpotifyOAuth(
        scope=_SCOPE,
        redirect_uri=redirect_uri,
        requests_timeout=10,
        cache_handler=spotipy.cache_handler.MemoryCacheHandler(),
    )


def get_client(user_id: str) -> Spotify | None:
    user = db.get_user(user_id)
    if user is None:
        print(f"user {user_id} not found")
        return None
    try:
        response = make_oauth("http://localhost").refresh_access_token(user.refresh_token)
    except Exception as exc:
        print(f"failed to refresh for user {user_id}: {exc}")
        return None
    if not response or "access_token" not in response:
        print(f"failed to refresh for user {user_id}")
        return None
    if "refresh_token" in response:
        db.put_user(db.User(id=user_id, refresh_token=response["refresh_token"]))
    return Spotify(response.get("access_token"), requests_session=_build_session())


def get_playlist_id(spotify: Spotify, playlist_name):
    results = spotify.current_user_playlists(limit=50, offset=0)

    for playlist in results["items"]:
        if playlist["name"] == playlist_name:
            return playlist["id"]

    while results["next"]:
        results = spotify.next(results)
        for playlist in results["items"]:
            if playlist["name"] == playlist_name:
                return playlist["id"]

    user = spotify.current_user()
    playlist = spotify.user_playlist_create(
        user["id"],
        playlist_name,
        public=False,
        description="A copy of this user's liked songs",
    )
    return playlist["id"]


def _batches(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _all_saved_track_uris(spotify: Spotify) -> list[str]:
    results = spotify.current_user_saved_tracks(limit=50, offset=0)
    uris = [t["track"]["uri"] for t in results["items"] if t.get("track")]
    while results["next"]:
        results = spotify.next(results)
        uris.extend(t["track"]["uri"] for t in results["items"] if t.get("track"))
    return uris


def _all_playlists(spotify: Spotify) -> list[dict]:
    results = spotify.current_user_playlists(limit=50, offset=0)
    items = list(results["items"])
    while results["next"]:
        results = spotify.next(results)
        items.extend(results["items"])
    return items


def _playlist_track_uris(spotify: Spotify, playlist_id: str) -> list[str]:
    results = spotify.playlist_items(playlist_id, limit=_API_PAGE, offset=0)
    uris = [i["track"]["uri"] for i in results["items"] if i.get("track")]
    while results["next"]:
        results = spotify.next(results)
        uris.extend(i["track"]["uri"] for i in results["items"] if i.get("track"))
    return uris


def _existing_syncify_playlists(spotify: Spotify) -> dict[str, dict]:
    """Existing 'Syncify ...' playlists keyed by name, with their current tracks."""
    out = {}
    for p in _all_playlists(spotify):
        if p["name"].startswith("Syncify "):
            out[p["name"]] = {
                "id": p["id"],
                "uris": _playlist_track_uris(spotify, p["id"]),
            }
    return out


def _longest_in_order(items: list[str], key) -> list[str]:
    """Longest subsequence of `items` whose `key` is strictly increasing
    (patience sorting, O(n log n)). Used to find the songs already in the right
    relative order so we leave them anchored and only move the rest."""
    if not items:
        return []
    keys = [key(x) for x in items]
    tails: list[int] = []  # tails[i]: index of the smallest tail of a length-i+1 run
    tail_keys: list[int] = []
    prev = [-1] * len(items)
    for i, k in enumerate(keys):
        j = bisect.bisect_left(tail_keys, k)
        if j == len(tail_keys):
            tail_keys.append(k)
            tails.append(i)
        else:
            tail_keys[j] = k
            tails[j] = i
        prev[i] = tails[j - 1] if j > 0 else -1
    result = []
    i = tails[-1]
    while i != -1:
        result.append(items[i])
        i = prev[i]
    result.reverse()
    return result


def _diff(current: list[str], target: list[str]):
    """Work needed to turn the ordered list `current` into `target`.

    Returns (to_remove, inserts):
      to_remove: uris to delete from the playlist
      inserts:   (position, [uris]) groups to add, applied left-to-right so the
                 final order matches `target` exactly

    Songs already in the correct relative order stay put (the anchor); songs
    that moved, e.g. an unliked-then-re-liked track that jumped to the top, are
    removed and re-inserted at their new spot rather than triggering a rewrite.
    """
    if current == target:
        return [], []
    target_set = set(target)
    pos = {uri: i for i, uri in enumerate(target)}
    kept = [u for u in current if u in target_set]
    anchor = _longest_in_order(kept, key=lambda u: pos[u])
    anchor_set = set(anchor)
    # Drop unliked songs and any retained song that is now out of order.
    to_remove = [u for u in current if u not in anchor_set]
    # Insert everything not anchored (new songs and moved songs) in place.
    inserts: list[tuple[int, list[str]]] = []
    ai = 0
    run: tuple[int, list[str]] | None = None
    for p, uri in enumerate(target):
        if ai < len(anchor) and anchor[ai] == uri:
            ai += 1
            if run:
                inserts.append(run)
                run = None
        elif run is not None and run[0] + len(run[1]) == p:
            run[1].append(uri)
        else:
            if run:
                inserts.append(run)
            run = (p, [uri])
    if run:
        inserts.append(run)
    return to_remove, inserts


def sync(spotify: Spotify):
    """Mirror the user's liked songs into 'Syncify k/N' playlists, writing only
    the differences. Yields progress as a fraction in [0.0, 1.0]."""
    # Read the liked songs and the existing playlist contents at the same time;
    # neither depends on the other, so we overlap the two paginated scans.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        liked_future = pool.submit(_all_saved_track_uris, spotify)
        existing_future = pool.submit(_existing_syncify_playlists, spotify)
        liked = liked_future.result()
        existing = existing_future.result()

    print(
        json.dumps(
            {
                "event": "sync_fetched",
                "liked_count": len(liked),
                "existing_playlist_count": len(existing),
                "existing_playlists": list(existing.keys()),
            }
        )
    )

    chunks = [liked[i : i + _PLAYLIST_SIZE] for i in range(0, len(liked), _PLAYLIST_SIZE)]
    total = len(chunks)

    # Plan every playlist up front so progress reflects only the songs that
    # actually change, not the whole library.
    plans = []
    for idx, target in enumerate(chunks, start=1):
        name = f"Syncify {idx}/{total}"
        if name in existing:
            playlist_id = existing[name]["id"]
            current = existing[name]["uris"]
        else:
            playlist_id = get_playlist_id(spotify, name)
            current = []
        to_remove, inserts = _diff(current, target)
        plans.append((playlist_id, to_remove, inserts))

    total_ops = sum(
        len(to_remove) + sum(len(i) for _, i in inserts)
        for _, to_remove, inserts in plans
    )
    print(
        json.dumps(
            {
                "event": "sync_planned",
                "num_playlists": total,
                "total_ops": total_ops,
                "plan": [
                    {
                        "playlist_id": pid,
                        "to_remove": len(rem),
                        "to_insert": sum(len(i) for _, i in ins),
                    }
                    for pid, rem, ins in plans
                ],
            }
        )
    )
    if total_ops == 0:
        yield 1.0
        return

    done = 0
    for plan_idx, (playlist_id, to_remove, inserts) in enumerate(plans):
        playlist_ops = len(to_remove) + sum(len(i) for _, i in inserts)
        print(
            json.dumps(
                {
                    "event": "playlist_write_start",
                    "playlist_idx": plan_idx,
                    "playlist_id": playlist_id,
                    "to_remove": len(to_remove),
                    "to_insert": sum(len(i) for _, i in inserts),
                    "playlist_ops": playlist_ops,
                    "done_before": done,
                    "total_ops": total_ops,
                }
            )
        )
        for batch in _batches(to_remove, _API_PAGE):
            spotify.playlist_remove_all_occurrences_of_items(playlist_id, batch)
            done += len(batch)
            print(json.dumps({"event": "batch_done", "op": "remove", "playlist_idx": plan_idx, "batch_size": len(batch), "done": done, "total_ops": total_ops}))
            yield done / total_ops
        for position, items in inserts:
            for batch in _batches(items, _API_PAGE):
                spotify.playlist_add_items(playlist_id, batch, position=position)
                position += len(batch)
                done += len(batch)
                print(json.dumps({"event": "batch_done", "op": "insert", "playlist_idx": plan_idx, "batch_size": len(batch), "done": done, "total_ops": total_ops}))
                yield done / total_ops
        print(
            json.dumps(
                {
                    "event": "playlist_write_done",
                    "playlist_idx": plan_idx,
                    "playlist_id": playlist_id,
                    "done": done,
                    "total_ops": total_ops,
                }
            )
        )
    yield 1.0


def get_liked_count(client: Spotify) -> int:
    return client.current_user_saved_tracks(limit=1)["total"]
