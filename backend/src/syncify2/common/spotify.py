import spotipy
from spotipy import Spotify

from syncify2.common import db

_SCOPE = "playlist-read-private,playlist-modify-private,user-library-read,playlist-modify-public"


def make_oauth(redirect_uri: str) -> spotipy.oauth2.SpotifyOAuth:
    return spotipy.oauth2.SpotifyOAuth(
        scope=_SCOPE,
        redirect_uri=redirect_uri,
        requests_timeout=10,
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
    return Spotify(response.get("access_token"))


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


def sync(spotify: Spotify):
    progress = 0

    results = spotify.current_user_saved_tracks(limit=50, offset=0)

    liked_track_uris_raw = []

    for track in results["items"]:
        liked_track_uris_raw.append(track["track"]["uri"])
    progress += len(results["items"])
    yield progress

    while results["next"]:
        results = spotify.next(results)
        for track in results["items"]:
            liked_track_uris_raw.append(track["track"]["uri"])
        progress += len(results["items"])
        yield progress

    track_uris = [
        liked_track_uris_raw[i : i + 10000]
        for i in range(0, len(liked_track_uris_raw), 10000)
    ]

    for playlist_num, playlist_chunk in enumerate(track_uris, start=1):
        playlist_id = get_playlist_id(
            spotify,
            "Syncify " + str(playlist_num) + "/" + str(len(track_uris)),
        )
        spotify.playlist_replace_items(playlist_id, [])

        chunks = [playlist_chunk[i : i + 50] for i in range(0, len(playlist_chunk), 50)]

        for chunk in chunks:
            spotify.playlist_add_items(playlist_id, chunk)
            progress += len(chunk)
            yield progress


def get_liked_count(client: Spotify) -> int:
    return client.current_user_saved_tracks(limit=1)["total"]
