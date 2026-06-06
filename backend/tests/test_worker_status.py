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
