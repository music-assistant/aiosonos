"""Tests for cleaning up a removed group's event subscriptions."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

from aiosonos.api.namespaces.audio_clip import AudioClipNameSpace
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


async def test_create_group_returns_the_group_info() -> None:
    """The created (or reused) group comes back to the caller."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._household_id = "Sonos_1"
    client.api = MagicMock()
    info = {"group": {"id": "group1", "playerIds": ["RINCON_A", "RINCON_B"]}}
    client.api.groups.create_group = AsyncMock(return_value=info)

    assert await client.create_group(["RINCON_A", "RINCON_B"]) == info
    client.api.groups.create_group.assert_awaited_once_with(
        "Sonos_1", ["RINCON_A", "RINCON_B"], None
    )


async def test_load_audio_clip_sends_only_given_options() -> None:
    """Optional clip parameters that were not given are left out, not sent as null."""
    api = MagicMock()
    api.send_command = AsyncMock(return_value={})
    namespace = AudioClipNameSpace(api)

    await namespace.load_audio_clip("RINCON_A", name="Hello", app_id="com.example")

    options = api.send_command.await_args.kwargs["options"]
    assert "streamUrl" not in options
    assert "httpAuthorization" not in options
    assert "volume" not in options
    assert options["name"] == "Hello"

    await namespace.load_audio_clip(
        "RINCON_A", name="Hello", app_id="com.example", stream_url="http://x/y.mp3", volume=0
    )
    options = api.send_command.await_args.kwargs["options"]
    assert options["streamUrl"] == "http://x/y.mp3"
    assert options["volume"] == 0


async def test_start_listening_without_ready_event() -> None:
    """The ready event is optional, as its signature says."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._player_id = "RINCON_ME"
    client._household_id = "Sonos_1"
    client._loop = asyncio.get_running_loop()
    api = MagicMock()
    api.start_listening = AsyncMock()
    api.groups.get_groups = AsyncMock(
        return_value={"groups": [], "players": [{"id": "RINCON_ME", "name": "Me"}]}
    )
    api.groups.subscribe = AsyncMock()
    api.player_volume.get_volume = AsyncMock(return_value={})
    api.player_volume.subscribe = AsyncMock()
    client.api = api

    await client.start_listening()

    assert client.player.id == "RINCON_ME"
