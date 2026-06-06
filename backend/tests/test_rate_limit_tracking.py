"""Tests that Spotify 429s are surfaced as logs + a CloudWatch EMF metric,
instead of being silently swallowed by spotipy's retry loop."""

import json

from syncify2.common import spotify


class _Resp:
    """Minimal stand-in for a urllib3 response, enough for Retry.increment."""

    def __init__(self, status, retry_after=None):
        self.status = status
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}

    def get_redirect_location(self):
        return False


def _emitted_metrics(capsys):
    out = []
    for line in capsys.readouterr().out.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def test_emit_429_is_valid_emf_with_the_metric(capsys):
    spotify._emit_429("5", "/v1/me/tracks")

    [record] = _emitted_metrics(capsys)
    assert record["RateLimited429"] == 1
    assert record["retryAfter"] == "5"
    assert record["path"] == "/v1/me/tracks"
    metric = record["_aws"]["CloudWatchMetrics"][0]
    assert metric["Namespace"] == "Syncify/Spotify"
    assert metric["Metrics"][0]["Name"] == "RateLimited429"


def test_retry_records_a_429(capsys):
    retry = spotify._LoggingRetry(
        total=3, status=3, status_forcelist=(429,), allowed_methods=frozenset(["GET"])
    )

    new = retry.increment(
        method="GET", url="/v1/me/tracks", response=_Resp(429, retry_after="3")
    )

    [record] = _emitted_metrics(capsys)
    assert record["RateLimited429"] == 1
    assert record["retryAfter"] == "3"
    # still behaves like a normal Retry (counter decremented, returns a Retry)
    assert isinstance(new, spotify._LoggingRetry)
    assert new.status == 2


def test_retry_ignores_non_429(capsys):
    retry = spotify._LoggingRetry(
        total=3, status=3, status_forcelist=(429, 500), allowed_methods=frozenset(["GET"])
    )

    retry.increment(method="GET", url="/v1/me/tracks", response=_Resp(500))

    assert _emitted_metrics(capsys) == []


def test_client_session_mounts_the_logging_retry():
    session = spotify._build_session()
    adapter = session.get_adapter("https://api.spotify.com/v1/me")
    assert isinstance(adapter.max_retries, spotify._LoggingRetry)
    assert 429 in adapter.max_retries.status_forcelist
