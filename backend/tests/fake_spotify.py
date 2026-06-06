"""A minimal in-memory fake of the spotipy Spotify client.

Models only the surface that syncify2.common.spotify uses, with the same
cursor-paging semantics: callers read a first page, then follow `page["next"]`
via `client.next(page)` until it is falsy. Here `next` simply holds the next
page dict (truthy when more pages remain), which is enough to drive the code.
"""

from dataclasses import dataclass, field


def _paginate(items, page_size, make_item):
    chunks = [items[i : i + page_size] for i in range(0, len(items), page_size)] or [[]]
    pages = [
        {"items": [make_item(x) for x in chunk], "total": len(items), "next": None}
        for chunk in chunks
    ]
    for i in range(len(pages) - 1):
        pages[i]["next"] = pages[i + 1]
    return pages[0]


@dataclass
class FakeSpotify:
    liked: list[str] = field(default_factory=list)
    playlists: list[dict] = field(default_factory=list)
    # playlist_id -> list of track uris currently in the playlist
    contents: dict[str, list[str]] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)
    _next_pid: int = 0

    # --- saved tracks ---

    def current_user_saved_tracks(self, limit=50, offset=0):
        self.calls.append(("current_user_saved_tracks", limit, offset))
        return _paginate(self.liked, limit, lambda uri: {"track": {"uri": uri}})

    # --- playlists ---

    def current_user_playlists(self, limit=50, offset=0):
        self.calls.append(("current_user_playlists", limit, offset))
        return _paginate(self.playlists, limit, lambda p: p)

    def current_user(self):
        self.calls.append(("current_user",))
        return {"id": "user-1"}

    def user_playlist_create(self, user_id, name, public=False, description=""):
        self.calls.append(("user_playlist_create", name))
        self._next_pid += 1
        pid = f"pl-{self._next_pid}"
        playlist = {"id": pid, "name": name}
        self.playlists.append(playlist)
        self.contents[pid] = []
        return playlist

    def playlist_items(self, playlist_id, limit=100, offset=0, fields=None):
        self.calls.append(("playlist_items", playlist_id, limit, offset))
        return _paginate(
            self.contents.get(playlist_id, []),
            limit,
            lambda uri: {"track": {"uri": uri}},
        )

    def playlist_replace_items(self, playlist_id, items):
        self.calls.append(("playlist_replace_items", playlist_id, len(items)))
        self.contents[playlist_id] = list(items)

    def playlist_add_items(self, playlist_id, items, position=None):
        self.calls.append(("playlist_add_items", playlist_id, len(items), position))
        current = self.contents.setdefault(playlist_id, [])
        if position is None:
            current.extend(items)
        else:
            current[position:position] = items

    def playlist_remove_all_occurrences_of_items(self, playlist_id, items):
        self.calls.append(
            ("playlist_remove_all_occurrences_of_items", playlist_id, len(items))
        )
        remove = set(items)
        self.contents[playlist_id] = [
            u for u in self.contents.get(playlist_id, []) if u not in remove
        ]

    # --- cursor paging ---

    def next(self, results):
        self.calls.append(("next",))
        return results["next"]

    # --- helpers for assertions ---

    def calls_named(self, name):
        return [c for c in self.calls if c[0] == name]
