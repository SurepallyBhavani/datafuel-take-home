"""How sweep.get_json handles the portal's replies: 429, 5xx, timeouts, 404 and bad JSON."""
import pytest
import requests

import sweep


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = "fake reply"
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


@pytest.fixture
def portal(monkeypatch):
    """Replace requests.get with a list of replies, and time.sleep with a list of the waits."""
    portal = {"replies": [], "sleeps": []}

    def fake_get(url, params=None, headers=None, timeout=None):
        reply = portal["replies"].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(sweep.requests, "get", fake_get)
    monkeypatch.setattr(sweep.time, "sleep", lambda seconds: portal["sleeps"].append(seconds))
    monkeypatch.setattr(sweep, "last_request", 0.0)
    return portal


def call(portal, replies):
    """Ask for one page with these replies queued. Returns (body, error, number of attempts)."""
    portal["replies"] = list(replies)
    counts = {"attempts": 0}
    body, error = sweep.get_json("/v1/stores", {"page": 1}, counts)
    return body, error, counts["attempts"]


OK = {"ok": True}


def test_429_waits_for_retry_after_then_succeeds(portal):
    body, error, attempts = call(portal, [FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(200, OK)])
    assert body == OK and error is None
    assert attempts == 2
    assert 3.0 in portal["sleeps"]


def test_429_without_a_usable_retry_after_waits_two_seconds(portal):
    for headers in [{}, {"Retry-After": "soon"}]:
        portal["sleeps"].clear()
        body, error, attempts = call(portal, [FakeResponse(429, headers=headers), FakeResponse(200, OK)])
        assert body == OK
        assert 2 in portal["sleeps"]


def test_429_every_time_gives_up_with_a_reason(portal):
    body, error, attempts = call(portal, [FakeResponse(429, headers={"Retry-After": "1"})] * sweep.MAX_ATTEMPTS)
    assert body is None
    assert attempts == sweep.MAX_ATTEMPTS
    assert "gave up after %d attempts" % sweep.MAX_ATTEMPTS in error and "HTTP 429" in error


def test_503_is_retried_with_growing_waits(portal):
    body, error, attempts = call(portal, [FakeResponse(503), FakeResponse(503), FakeResponse(200, OK)])
    assert body == OK and attempts == 3
    assert 1 in portal["sleeps"] and 2 in portal["sleeps"]       # backoff: 1 second, then 2


def test_500_is_retried(portal):
    body, error, attempts = call(portal, [FakeResponse(500), FakeResponse(200, OK)])
    assert body == OK and attempts == 2


@pytest.mark.parametrize("status", [400, 401, 404])
def test_client_errors_are_not_retried(portal, status):
    body, error, attempts = call(portal, [FakeResponse(status)])
    assert body is None and attempts == 1
    assert error.startswith("HTTP %d" % status)


def test_timeout_and_connection_errors_are_retried(portal):
    body, error, attempts = call(portal, [requests.Timeout(), requests.ConnectionError(), FakeResponse(200, OK)])
    assert body == OK and attempts == 3


def test_a_reply_that_is_not_json_is_retried(portal):
    body, error, attempts = call(portal, [FakeResponse(200, body=None), FakeResponse(200, OK)])
    assert body == OK and attempts == 2


def test_gives_up_after_the_attempt_limit_with_the_last_error(portal):
    body, error, attempts = call(portal, [FakeResponse(503)] * sweep.MAX_ATTEMPTS)
    assert body is None and attempts == sweep.MAX_ATTEMPTS
    assert error == "gave up after %d attempts, last error: HTTP 503" % sweep.MAX_ATTEMPTS


def test_requests_are_spaced_out(portal):
    call(portal, [FakeResponse(503), FakeResponse(200, OK)])
    assert any(0 < wait <= sweep.GAP for wait in portal["sleeps"])
