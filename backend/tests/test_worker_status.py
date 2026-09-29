"""Worker status-transition tests.

Exercises syncify2.worker.worker._sync against fakes for db, spotify, scheduling
to assert the pending -> running -> {completed, failed} lifecycle that the
frontend now drives off.
"""

import pytest

from syncify2.worker import worker
from syncify2.common import db


class FakeDb:
    def __init__(self):
        self.calls: list[tuple] = []

    def mark_request_running(self, user_id, request_id):
        self.calls.append(("running", request_id))

    def mark_request_failed(self, user_id, request_id):
        self.calls.append(("failed", request_id))

    def complete_request(self, user_id, request_id):
        self.calls.append(("completed", request_id))

    def update_request_song_count(self, user_id, request_id, count):
        self.calls.append(("song_count", request_id, count))

    @property
    def statuses(self) -> list[str]:
        return [c[0] for c in self.calls if c[0] in {"running", "completed", "failed"}]


class FakeSpotifyModule:
    def __init__(self, count: int, sync_raises: Exception | None = None):
        self._count = count
        self._raises = sync_raises

    def get_client(self, user_id):
        return object()

    def get_liked_count(self, client):
        return self._count

    def sync(self, client):
        if self._raises:
            raise self._raises
        # Yield a couple of values to ensure the worker drains the generator
        # without inspecting them.
        yield 0.5
        yield 1.0


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDb()
    for name in (
        "mark_request_running",
        "mark_request_failed",
        "complete_request",
        "update_request_song_count",
    ):
        monkeypatch.setattr(worker.db, name, getattr(fake, name))
    return fake


def _make_request():
    return db.SyncRequest(
        id="req-1",
        user_id="u",
        song_count=100,
        status="pending",
        created="2026-01-01T00:00:00Z",
        completed=None,
    )


def test_successful_sync_transitions_pending_running_completed(monkeypatch, fake_db):
    monkeypatch.setattr(worker, "spotify", FakeSpotifyModule(count=100))
    monkeypatch.setattr(worker, "posthog", type("P", (), {"capture": staticmethod(lambda *a, **k: None)}))

    worker._sync("u", _make_request(), client=None)

    assert fake_db.statuses == ["running", "completed"]


def test_failure_during_sync_marks_failed_and_reraises(monkeypatch, fake_db):
    boom = RuntimeError("spotify exploded")
    monkeypatch.setattr(worker, "spotify", FakeSpotifyModule(count=100, sync_raises=boom))

    with pytest.raises(RuntimeError, match="spotify exploded"):
        worker._sync("u", _make_request(), client=None)

    # We marked running first, then failed when the exception bubbled.
    assert fake_db.statuses == ["running", "failed"]


def test_empty_library_completes_without_marking_running(monkeypatch, fake_db):
    monkeypatch.setattr(worker, "spotify", FakeSpotifyModule(count=0))

    worker._sync("u", _make_request(), client=None)

    # Empty library short-circuits before the sync loop, so we never hit running.
    assert fake_db.statuses == ["completed"]


def test_failure_records_completed_at(monkeypatch):
    updates = {}

    class _Table:
        def update_item(self, **kwargs):
            updates.update(kwargs)

        def delete_item(self, **kwargs):
            updates["deleted"] = kwargs["Key"]

    monkeypatch.setattr(db, "_requests_table", _Table())

    db.mark_request_failed("u", "req-1")

    assert "completedAt" in updates["UpdateExpression"]
    assert updates["ExpressionAttributeValues"][":v"] == "failed"
    assert updates["deleted"] == {"userId": "u", "requestId": "#lock"}


def test_four_slices_without_finishing_fails_the_request():
    from syncify2.worker.workflow import SLICE_NAMES, run_workflow

    steps = []
    failed = []

    def step(name, fn):
        steps.append(name)
        return fn()

    status = run_workflow(
        "u",
        "req-1",
        step,
        lambda name, seconds: None,
        lambda index: {"done": False, "wait_seconds": 0, "cursor_moved": True},
        lambda: failed.append("failed"),
    )

    assert status == "failed"
    assert steps == list(SLICE_NAMES)
    assert failed == ["failed"]


def test_slice_with_no_progress_fails_immediately():
    from syncify2.worker.workflow import run_workflow

    steps = []
    failed = []

    status = run_workflow(
        "u",
        "req-1",
        lambda name, fn: steps.append(name) or fn(),
        lambda name, seconds: None,
        lambda index: {"done": False, "wait_seconds": 0, "cursor_moved": False},
        lambda: failed.append("failed"),
    )

    assert status == "failed"
    assert steps == ["slice-1"]
    assert failed == ["failed"]


def test_long_rate_limit_waits_then_continues():
    from syncify2.worker.workflow import run_workflow

    results = iter(
        [
            {"done": False, "wait_seconds": 30, "cursor_moved": True},
            {"done": True, "wait_seconds": 0, "cursor_moved": True},
        ]
    )
    waits = []

    status = run_workflow(
        "u",
        "req-1",
        lambda name, fn: fn(),
        lambda name, seconds: waits.append((name, seconds)),
        lambda index: next(results),
        lambda: None,
    )

    assert status == "completed"
    assert waits == [("wait-after-slice-1", 30)]


class _Request:
    def __init__(self, status="pending", completed=None, song_count=250):
        self.status = status
        self.completed = completed
        self.song_count = song_count
        self.phase = None


class _Slices:
    def __init__(self):
        self.objects = {}

    def load(self, user_id, request_id, slice_index):
        return self.objects.get((user_id, request_id, slice_index))

    def save(self, user_id, request_id, slice_index, state):
        self.objects[(user_id, request_id, slice_index)] = state


def _patch_slice(monkeypatch, client, request, slices):
    from syncify2.worker import slice_runner

    monkeypatch.setattr(slice_runner.spotify, "get_client", lambda user_id: client)
    monkeypatch.setattr(slice_runner.checkpoints, "load_slice", slices.load)
    monkeypatch.setattr(slice_runner.checkpoints, "save_slice", slices.save)
    monkeypatch.setattr(slice_runner.posthog, "capture", lambda *a, **k: None)
    monkeypatch.setattr(slice_runner.db, "get_request", lambda *a: request)
    monkeypatch.setattr(slice_runner.db, "mark_request_running", lambda *a: None)
    monkeypatch.setattr(
        slice_runner.db, "update_request_song_count", lambda *a: None
    )
    monkeypatch.setattr(slice_runner.db, "release_sync_slot", lambda *a: None)
    monkeypatch.setattr(slice_runner.db, "complete_request", lambda *a: setattr(request, "status", "completed") or setattr(request, "completed", "t"))

    def save_progress(*args, **kwargs):
        request.phase = kwargs["phase"]
        request.status = "running"
        return True

    monkeypatch.setattr(slice_runner.db, "save_progress", save_progress)
    return slice_runner


def test_replay_continues_from_the_saved_liked_offset(monkeypatch):
    from tests.fake_spotify import FakeSpotify

    songs = [f"spotify:track:{i:05d}" for i in range(250)]
    client = FakeSpotify(liked=songs)
    request = _Request(song_count=250)
    slices = _Slices()
    runner = _patch_slice(monkeypatch, client, request, slices)

    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return 0 if ticks["n"] <= 4 else 10**9

    first = runner.run_slice("u", "req-1", 0, clock=clock, deadline=1)
    assert first.done is False
    assert [call[2] for call in client.calls_named("current_user_saved_tracks")] == [
        0,
        50,
        100,
        150,
    ]

    client.calls.clear()
    ticks["n"] = 0
    runner.run_slice("u", "req-1", 0, clock=clock, deadline=1)
    offsets = [call[2] for call in client.calls_named("current_user_saved_tracks")]
    assert 0 not in offsets
    assert offsets[0] == 200


def test_missing_request_does_not_call_spotify(monkeypatch):
    from syncify2.worker import slice_runner

    called = []
    monkeypatch.setattr(
        slice_runner.spotify, "get_client", lambda user_id: called.append(user_id)
    )
    monkeypatch.setattr(slice_runner.db, "get_request", lambda *a: None)
    released = []
    monkeypatch.setattr(
        slice_runner.db, "release_sync_slot", lambda user_id: released.append(user_id)
    )

    result = slice_runner.run_slice("u", "req-1", 0)

    assert result.done is True
    assert called == []
    assert released == ["u"]


def test_stopped_request_does_not_start_another_sync(monkeypatch):
    from syncify2.worker import slice_runner

    called = []
    monkeypatch.setattr(
        slice_runner.spotify, "get_client", lambda user_id: called.append(user_id)
    )
    monkeypatch.setattr(
        slice_runner.db,
        "get_request",
        lambda *a: _Request(status="failed", completed="t"),
    )

    result = slice_runner.run_slice("u", "req-1", 0)

    assert result.done is True
    assert called == []


def test_small_library_finishes_inside_one_slice(monkeypatch):
    from tests.fake_spotify import FakeSpotify

    songs = [f"spotify:track:{i:05d}" for i in range(3)]
    client = FakeSpotify(liked=songs)
    request = _Request(song_count=3)
    runner = _patch_slice(monkeypatch, client, request, _Slices())
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return ticks["n"]

    result = runner.run_slice("u", "req-1", 0, clock=clock, deadline=200)

    assert ticks["n"] < 200
    assert result.done is True
    assert request.status == "completed"
    assert request.completed == "t"
    ordered = sorted(
        (p for p in client.playlists if p["name"].startswith("Syncify ")),
        key=lambda p: int(p["name"].split()[1].split("/")[0]),
    )
    contents = []
    for playlist in ordered:
        contents.extend(client.contents[playlist["id"]])
    assert contents == songs


def test_dispatcher_skips_a_missing_or_finished_request(monkeypatch):
    from botocore.exceptions import ClientError

    from syncify2.worker import lambda_handler

    invoked = []

    class _Lambda:
        def invoke(self, **kwargs):
            invoked.append(kwargs)
            raise ClientError(
                {
                    "Error": {
                        "Code": "DurableExecutionAlreadyStartedException",
                        "Message": "exists",
                    }
                },
                "Invoke",
            )

    monkeypatch.setattr(lambda_handler, "_lambda", _Lambda())
    monkeypatch.setattr(lambda_handler.db, "get_request", lambda *a: None)
    lambda_handler._dispatch({"user_id": "u", "request_id": "req-1"})
    assert invoked == []

    monkeypatch.setattr(
        lambda_handler.db,
        "get_request",
        lambda *a: _Request(status="failed", completed="t"),
    )
    lambda_handler._dispatch({"user_id": "u", "request_id": "req-1"})
    assert invoked == []

    monkeypatch.setattr(
        lambda_handler.db, "get_request", lambda *a: _Request(status="running")
    )
    monkeypatch.setattr(lambda_handler.db, "set_execution_arn", lambda *a: None)
    lambda_handler._dispatch({"user_id": "u", "request_id": "req-1"})
    assert invoked[0]["DurableExecutionName"] == "req-1"
    assert invoked[0]["InvocationType"] == "Event"
