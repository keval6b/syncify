"""Correctness tests for syncify2.common.spotify.

These assert the OUTCOME of a sync: after running, do the Syncify playlists
contain exactly the user's liked songs, in order, split correctly, and does a
re-sync converge to the right set when the library changes? They say nothing
about how many API calls it takes; only whether the result is correct.
"""

from syncify2.common import spotify
from tests.fake_spotify import FakeSpotify


def uris(n, prefix="spotify:track:"):
    return [f"{prefix}{i:05d}" for i in range(n)]


def synced_contents(client):
    """The full set of songs across all Syncify playlists, in playlist order
    (1/N, 2/N, ...), concatenated, as they stand after a sync."""
    ordered = sorted(
        (p for p in client.playlists if p["name"].startswith("Syncify ")),
        key=lambda p: int(p["name"].split()[1].split("/")[0]),
    )
    result = []
    for p in ordered:
        result.extend(client.contents[p["id"]])
    return result


# --- the core question: are the right songs in the playlist? ---


def test_all_liked_songs_end_up_in_the_playlist():
    songs = uris(120)
    client = FakeSpotify(liked=songs)

    list(spotify.sync(client))

    assert synced_contents(client) == songs


def test_song_order_is_preserved():
    songs = uris(75)
    client = FakeSpotify(liked=songs)

    list(spotify.sync(client))

    assert synced_contents(client) == songs


def test_no_songs_dropped_or_duplicated_across_page_boundaries():
    # 230 songs spans several 50-item read pages and 50-item write chunks
    songs = uris(230)
    client = FakeSpotify(liked=songs)

    list(spotify.sync(client))

    result = synced_contents(client)
    assert result == songs
    assert len(result) == len(set(result)) == 230


# --- splitting large libraries across playlists ---


def test_library_over_10k_splits_but_keeps_every_song():
    songs = uris(10001)
    client = FakeSpotify(liked=songs)

    list(spotify.sync(client))

    names = sorted(p["name"] for p in client.playlists)
    assert names == ["Syncify 1/2", "Syncify 2/2"]
    # every song present exactly once, in order, across both playlists
    assert synced_contents(client) == songs


# --- re-syncing converges to the current liked set ---


def test_resync_unchanged_library_keeps_exact_songs():
    songs = uris(200)
    client = FakeSpotify(
        liked=songs,
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": list(songs)},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == songs


def test_resync_reflects_newly_added_songs():
    client = FakeSpotify(
        liked=uris(100),
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": uris(80)},  # last sync only had 80
    )

    list(spotify.sync(client))

    assert synced_contents(client) == uris(100)


def test_resync_drops_removed_songs():
    # user previously had 100 liked, now only the first 60 remain liked
    client = FakeSpotify(
        liked=uris(60),
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": uris(100)},
    )

    list(spotify.sync(client))

    result = synced_contents(client)
    assert result == uris(60)
    # the 40 unliked songs are gone
    assert not any(u in result for u in uris(100)[60:])


def test_resync_reuses_playlist_instead_of_creating_duplicate():
    client = FakeSpotify(
        liked=uris(50),
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": uris(50)},
    )

    list(spotify.sync(client))

    syncify_playlists = [p for p in client.playlists if p["name"] == "Syncify 1/1"]
    assert len(syncify_playlists) == 1
    assert syncify_playlists[0]["id"] == "pl-old"


# --- the diff only touches what changed ---


def test_unchanged_library_writes_nothing():
    """An up-to-date playlist must not be re-uploaded: zero add/remove/replace."""
    client = FakeSpotify(
        liked=uris(300),
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": uris(300)},
    )

    list(spotify.sync(client))

    assert client.calls_named("playlist_add_items") == []
    assert client.calls_named("playlist_remove_all_occurrences_of_items") == []
    assert client.calls_named("playlist_replace_items") == []


def test_newly_liked_song_at_front_keeps_mirror_order():
    # Spotify returns liked songs newest-first, so a new like lands at the top.
    client = FakeSpotify(
        liked=["d", "a", "b", "c"],
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": ["a", "b", "c"]},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == ["d", "a", "b", "c"]


def test_only_the_changed_songs_are_written():
    # c removed, e added; a, b, d stay put
    client = FakeSpotify(
        liked=["a", "b", "e", "d"],
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": ["a", "b", "c", "d"]},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == ["a", "b", "e", "d"]
    removes = client.calls_named("playlist_remove_all_occurrences_of_items")
    adds = client.calls_named("playlist_add_items")
    # exactly one song removed and one added
    assert sum(c[2] for c in removes) == 1
    assert sum(c[2] for c in adds) == 1


def test_reordered_library_still_ends_up_correct():
    client = FakeSpotify(
        liked=["c", "b", "a"],
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": ["a", "b", "c"]},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == ["c", "b", "a"]


def test_relike_moves_one_song_without_full_rewrite():
    # User re-likes c, so it jumps to the top of the liked list.
    client = FakeSpotify(
        liked=["c", "a", "b", "d"],
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": ["a", "b", "c", "d"]},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == ["c", "a", "b", "d"]
    # never wipes the playlist...
    assert client.calls_named("playlist_replace_items") == []
    # ...and only c is touched: removed from the middle, re-inserted at the top
    removes = client.calls_named("playlist_remove_all_occurrences_of_items")
    adds = client.calls_named("playlist_add_items")
    assert sum(c[2] for c in removes) == 1
    assert sum(c[2] for c in adds) == 1
    assert adds[0][3] == 0  # inserted at position 0


def test_moving_one_song_among_many_touches_only_that_song():
    # 500 songs in order; song #400 gets re-liked and jumps to the front.
    songs = uris(500)
    moved = songs[400]
    client = FakeSpotify(
        liked=[moved] + [s for s in songs if s != moved],
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": songs},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == [moved] + [s for s in songs if s != moved]
    # one remove + one insert, not a 500-song rewrite
    removes = client.calls_named("playlist_remove_all_occurrences_of_items")
    adds = client.calls_named("playlist_add_items")
    assert sum(c[2] for c in removes) == 1
    assert sum(c[2] for c in adds) == 1
    assert client.calls_named("playlist_replace_items") == []


def test_removing_middle_item_maintains_order():
    client = FakeSpotify(
        liked=["a", "b", "d", "e"],  # c removed from the middle
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": ["a", "b", "c", "d", "e"]},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == ["a", "b", "d", "e"]
    removes = client.calls_named("playlist_remove_all_occurrences_of_items")
    assert sum(c[2] for c in removes) == 1  # only c removed
    assert client.calls_named("playlist_add_items") == []  # nothing re-added


def test_adding_item_at_end_adds_one_item_at_end():
    client = FakeSpotify(
        liked=["a", "b", "c", "d"],  # d appended at the end
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": ["a", "b", "c"]},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == ["a", "b", "c", "d"]
    adds = client.calls_named("playlist_add_items")
    assert len(adds) == 1
    _, pid, n, position = adds[0]
    assert n == 1 and position == 3  # one item, inserted after the existing three
    assert client.calls_named("playlist_remove_all_occurrences_of_items") == []


def test_adding_item_in_the_middle_is_handled():
    client = FakeSpotify(
        liked=["a", "b", "c", "d"],  # c inserted into the middle
        playlists=[{"id": "pl-old", "name": "Syncify 1/1"}],
        contents={"pl-old": ["a", "b", "d"]},
    )

    list(spotify.sync(client))

    assert synced_contents(client) == ["a", "b", "c", "d"]
    adds = client.calls_named("playlist_add_items")
    assert len(adds) == 1
    _, pid, n, position = adds[0]
    assert n == 1 and position == 2  # inserted at index 2, between b and d
    assert client.calls_named("playlist_remove_all_occurrences_of_items") == []


def test_progress_is_a_fraction_ending_at_one():
    client = FakeSpotify(liked=uris(120))

    progress = list(spotify.sync(client))

    assert progress == sorted(progress)
    assert all(0.0 <= p <= 1.0 for p in progress)
    assert progress[-1] == 1.0


def test_diff_transforms_current_into_target_for_random_mutations():
    """Fuzz the diff: applying its remove + insert ops to any `current` must
    reproduce `target` exactly (arbitrary adds, removes, and reorders)."""
    import random

    rng = random.Random(1234)
    pool = uris(40)
    for _ in range(2000):
        current = rng.sample(pool, rng.randint(0, len(pool)))
        target = rng.sample(pool, rng.randint(0, len(pool)))

        to_remove, inserts = spotify._diff(current, target)

        # apply the plan exactly as sync would: remove first, then insert
        # each group left-to-right at its position
        live = [u for u in current if u not in set(to_remove)]
        for position, items in inserts:
            live[position:position] = items

        assert live == target, f"current={current} target={target} got={live}"


# --- counting ---


def test_get_liked_count_matches_library_size():
    assert spotify.get_liked_count(FakeSpotify(liked=uris(137))) == 137
    assert spotify.get_liked_count(FakeSpotify(liked=[])) == 0
