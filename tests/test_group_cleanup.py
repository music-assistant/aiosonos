"""Tests for cleaning up a removed group's event subscriptions."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

from aiosonos.api.namespaces.audio_clip import AudioClipNameSpace
from aiosonos.client import SonosLocalApiClient
from aiosonos.const import EventType
from aiosonos.exceptions import InvalidState
from aiosonos.group import SonosGroup
from aiosonos.player import SonosPlayer


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


def test_partial_groups_event_removes_nothing() -> None:
    """A groups event flagged partial lists an incomplete household; nothing is torn down."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client.signal_event = MagicMock()
    client._player_id = "RINCON_ME"
    client._player = MagicMock()
    group = MagicMock()
    group.id = "group1"
    client._groups = {"group1": group}

    client._handle_groups_event({"groups": [], "players": [], "partial": True})

    group.cleanup.assert_not_called()
    assert client._groups == {"group1": group}
    client.signal_event.assert_not_called()


def _player_with_groups(groups: list[MagicMock]) -> SonosPlayer:
    client = MagicMock()
    client.groups = groups
    client.player_id = "RINCON_ME"
    return SonosPlayer(client, {"id": "RINCON_ME", "name": "Me"})


def _member_group(group_id: str, player_ids: list[str]) -> MagicMock:
    group = MagicMock()
    group.id = group_id
    group.coordinator_id = player_ids[0]
    group.player_ids = player_ids
    return group


def test_player_in_no_group_has_no_active_group() -> None:
    """A player no listed group contains ends up without a group instead of raising."""
    player = _player_with_groups([_member_group("other", ["RINCON_OTHER"])])

    player.check_active_group()

    assert player.group is None
    assert not player.is_coordinator
    assert not player.is_passive
    assert player.group_members == []


def test_player_drops_group_that_no_longer_lists_it() -> None:
    """A group the player left (or that was removed) is let go, and the change is signalled."""
    mine = _member_group("group1", ["RINCON_ME"])
    player = _player_with_groups([mine])
    assert player.group is mine

    player.client.groups = [_member_group("other", ["RINCON_OTHER"])]
    player.check_active_group()

    assert player.group is None
    event = player.client.signal_event.call_args.args[0]
    assert event.event_type == EventType.PLAYER_UPDATED
    assert event.object_id == "RINCON_ME"


def test_player_picks_up_group_it_joined() -> None:
    """A player that reappears in a group gets that group and signals the change once."""
    player = _player_with_groups([])
    assert player.group is None
    mine = _member_group("group1", ["RINCON_ME"])

    player.client.groups = [mine]
    player.check_active_group()
    player.check_active_group()

    assert player.group is mine
    assert player.client.signal_event.call_count == 1


async def test_partial_event_moving_the_player_wins_over_its_cached_group() -> None:
    """A partial event that lists the player in group B moves it there from omitted group A."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._player_id = "RINCON_ME"
    client._loop = asyncio.get_running_loop()
    client.signal_event = MagicMock()
    client.api = MagicMock()
    client.api.groups.modify_group_members = AsyncMock()
    group_a = SonosGroup(
        client, {"id": "A", "coordinatorId": "RINCON_ME", "playerIds": ["RINCON_ME"]}
    )
    group_b = SonosGroup(
        client, {"id": "B", "coordinatorId": "RINCON_OTHER", "playerIds": ["RINCON_OTHER"]}
    )
    client._groups = {"A": group_a, "B": group_b}
    client._player = SonosPlayer(client, {"id": "RINCON_ME", "name": "Me"})
    assert client.player.group is group_a

    client._handle_groups_event(
        {
            "groups": [
                {
                    "id": "B",
                    "coordinatorId": "RINCON_OTHER",
                    "playerIds": ["RINCON_OTHER", "RINCON_ME"],
                }
            ],
            "players": [{"id": "RINCON_ME", "name": "Me"}],
            "partial": True,
        }
    )
    await client.player.leave_group()

    assert client._groups == {"A": group_a, "B": group_b}
    assert group_a.player_ids == []
    assert client.player.group is group_b
    client.api.groups.modify_group_members.assert_awaited_once_with(
        "B", player_ids_to_add=[], player_ids_to_remove=["RINCON_ME"]
    )


def test_a_group_listing_the_player_wins_over_one_it_only_coordinated() -> None:
    """A cached group that still names the player as coordinator does not hide its real group."""
    stale = _member_group("A", ["RINCON_ME"])
    stale.player_ids = ["RINCON_OTHER"]
    real = _member_group("B", ["RINCON_OTHER", "RINCON_ME"])
    player = _player_with_groups([stale, real])

    player.check_active_group()

    assert player.group is real


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
