"""Tests for cleaning up a removed group's event subscriptions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

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


async def test_normal_add_signals_group_added_once() -> None:
    """A successful group setup signals GROUP_ADDED exactly once."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client.signal_event = MagicMock()
    api = MagicMock()
    api.group_volume.get_volume = AsyncMock(return_value={})
    api.playback.get_playback_status = AsyncMock(
        return_value={"availablePlaybackActions": {}, "playModes": {}},
    )
    api.playback_metadata.get_metadata_status = AsyncMock(return_value={})
    api.playback.subscribe = AsyncMock(return_value=Mock())
    api.group_volume.subscribe = AsyncMock(return_value=Mock())
    api.playback_metadata.subscribe = AsyncMock(return_value=Mock())
    client.api = api

    await client._setup_group({"id": "group1"})

    client.signal_event.assert_called_once()
    event = client.signal_event.call_args.args[0]
    assert event.event_type == EventType.GROUP_ADDED
    assert event.object_id == "group1"


async def test_group_removed_during_setup_is_cleaned_up() -> None:
    """A group removed while async_init is in flight is cleaned up, not left with live listeners."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client.signal_event = MagicMock()
    group = MagicMock()
    group.id = "group1"

    def _remove_group() -> None:
        # simulate a removal event arriving while async_init is still running
        client._groups.pop("group1")

    group.async_init = AsyncMock(side_effect=_remove_group)
    client._groups = {"group1": group}

    await client._setup_group({"id": "group1"})

    group.cleanup.assert_called_once()
    client.signal_event.assert_not_called()
