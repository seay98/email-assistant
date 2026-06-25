from pathlib import Path
from types import SimpleNamespace
import re
import sys


OUTLOOK_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "email_assistant"
    / "tools"
    / "outlook"
)
sys.path.insert(0, str(OUTLOOK_DIR))

import outlook_tools  # noqa: E402
from outlook_tools import _build_filter  # noqa: E402


def _args(**overrides):
    defaults = {
        "hours_since": 2,
        "include_read": False,
        "no_time_filter": False,
        "skip_filters": False,
        "skip_email_filter": False,
        "email": None,
        "fetch_limit": 25,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_default_filter_limits_to_recent_unread_messages():
    filter_query = _build_filter(_args())

    assert re.search(r"receivedDateTime ge .*Z", filter_query)
    assert "isRead eq false" in filter_query
    assert " and " in filter_query


def test_include_read_keeps_time_filter_only():
    filter_query = _build_filter(_args(include_read=True))

    assert re.search(r"receivedDateTime ge .*Z", filter_query)
    assert "isRead eq false" not in filter_query


def test_hours_since_zero_with_include_read_disables_server_filter():
    assert _build_filter(_args(hours_since=0, include_read=True)) == ""


def test_no_time_filter_with_unread_default_keeps_read_filter():
    assert _build_filter(_args(no_time_filter=True)) == "isRead eq false"


def test_skip_filters_disables_server_filter():
    assert _build_filter(_args(skip_filters=True)) is None


def _messages():
    return [
        {
            "id": "message-1",
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "user@example.com"}}],
        },
        {
            "id": "message-2",
            "from": {"emailAddress": {"address": "list@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "team@example.com"}}],
        },
    ]


def _patch_graph_request(monkeypatch):
    def fake_graph_request(method, url, token_data, params=None):
        return {"value": _messages()}

    monkeypatch.setattr(outlook_tools, "graph_request", fake_graph_request)


def test_fetch_without_email_returns_all_messages(monkeypatch):
    _patch_graph_request(monkeypatch)

    messages = outlook_tools.fetch_outlook_messages(
        _args(email=None, include_read=True, hours_since=0),
        {"access_token": "token"},
    )

    assert [message["id"] for message in messages] == ["message-1", "message-2"]


def test_fetch_with_email_filters_by_sender_or_recipient(monkeypatch):
    _patch_graph_request(monkeypatch)

    messages = outlook_tools.fetch_outlook_messages(
        _args(email="user@example.com", include_read=True, hours_since=0),
        {"access_token": "token"},
    )

    assert [message["id"] for message in messages] == ["message-1"]


def test_fetch_with_skip_email_filter_returns_all_messages(monkeypatch):
    _patch_graph_request(monkeypatch)

    messages = outlook_tools.fetch_outlook_messages(
        _args(
            email="user@example.com",
            include_read=True,
            hours_since=0,
            skip_email_filter=True,
        ),
        {"access_token": "token"},
    )

    assert [message["id"] for message in messages] == ["message-1", "message-2"]
