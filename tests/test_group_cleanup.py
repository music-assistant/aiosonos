"""Tests for cleaning up a removed group's event subscriptions."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

from aiosonos.client import SonosLocalApiClient
from aiosonos.const import EventType
from aiosonos.exceptions import InvalidState
from aiosonos.group import SonosGroup


def test_cleanup_tolerates_disconnected_unsubscribe() -> None:
    """cleanup() unsubscribes every listener and clears the list, even when one fails."""
    group = SonosGroup(MagicMock(), {"id": "group1"})
    failing = Mock(side_effect=InvalidState("Not connected"))
    ok = Mock()
    group._unsubscribe_callbacks = [failing, ok]

    group.cleanup()

    # a failing unsubscribe must not stop the remaining ones from running
    failing.assert_called_once()
    ok.assert_called_once()
    assert group._unsubscribe_callbacks == []


def test_removed_group_is_cleaned_up() -> None:
    """A group missing from a groups event is cleaned up and removed."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client.signal_event = MagicMock()
    group = MagicMock()
    client._groups = {"group1": group}

    client._handle_groups_event({"groups": [], "players": []})

    group.cleanup.assert_called_once()
    assert "group1" not in client._groups
    client.signal_event.assert_called_once()
    event = client.signal_event.call_args.args[0]
    assert event.event_type == EventType.GROUP_REMOVED
    assert event.object_id == "group1"
