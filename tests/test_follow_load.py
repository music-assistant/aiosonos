"""Tests for reading the playback status after a load, while the player holds its events back."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from aiosonos.api.models import PlayBackState
from aiosonos.client import SonosLocalApiClient
from aiosonos.const import EventType
from aiosonos.exceptions import CommandTimeout, FailedCommand, InvalidState
from aiosonos.group import SonosGroup

if TYPE_CHECKING:
    from aiosonos.api.models import Container

PLAYER = "RINCON_F0F6C1CC8D0401400"
ITEM = "item1@100"


@pytest.fixture(autouse=True)
def _short_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aiosonos.group.LOAD_STATUS_DELAYS", (0.01,) * 4)


def _status(state: str, item_id: str | None = ITEM, position: int = 0) -> dict[str, Any]:
    """Build a playbackStatus as the speaker sends it in a reply or an event."""
    status: dict[str, Any] = {
        "_objectType": "playbackStatus",
        "availablePlaybackActions": {"canPause": state != "IDLE"},
        "isDucking": False,
        "playbackState": f"PLAYBACK_STATE_{state}",
        "playModes": {"repeat": False},
        "positionMillis": position,
        "previousPositionMillis": 0,
    }
    if item_id is not None:
        status["itemId"] = item_id
    return status


def _group(*replies: dict[str, Any] | Exception) -> tuple[SonosGroup, AsyncMock]:
    """Build a group and the status read it uses, which gives the replies in turn."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._player_id = PLAYER
    client.signal_event = MagicMock()
    client.api = MagicMock(connected=True)
    session = client.api.playback_session
    session.create_session = AsyncMock(
        side_effect=[{"sessionId": "session1"}, {"sessionId": "session2"}]
    )
    session.subscribe = AsyncMock(side_effect=lambda *_: Mock())
    session.leave_session = AsyncMock()
    session.load_cloud_queue = AsyncMock()
    session.load_stream_url = AsyncMock()
    read = AsyncMock(side_effect=list(replies))
    client.api.playback.get_playback_status = read
    group = SonosGroup(client, {"id": "group1", "coordinatorId": PLAYER, "playerIds": [PLAYER]})
    return group, read


async def _followed(group: SonosGroup) -> None:
    """Wait until the group is done following its load."""
    assert group._load_follower is not None
    async with asyncio.timeout(2):
        await asyncio.wait([group._load_follower])
    assert group._load_follower.cancelled() or group._load_follower.exception() is None


async def test_a_load_is_seen_playing_without_an_event() -> None:
    """The status is read after a load until the group plays, and signalled as an event would be."""
    group, read = _group(_status("BUFFERING"), _status("PLAYING", position=272))

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    await _followed(group)

    assert read.await_count == 2
    read.assert_awaited_with("group1")
    assert group.playback_state == PlayBackState.PLAYBACK_STATE_PLAYING
    assert group.position == pytest.approx(0.272, abs=0.2)
    assert group.playback_actions.can_pause
    signalled = [call.args[0].event_type for call in group.client.signal_event.call_args_list]
    assert signalled == [EventType.GROUP_UPDATED, EventType.GROUP_UPDATED]


async def test_a_stream_is_followed_as_well() -> None:
    """A stream URL load is followed like a cloud queue."""
    group, read = _group(_status("PLAYING", item_id=None))

    await group.play_stream_url("https://stream", cast("Container", {}))
    await _followed(group)

    assert read.await_count == 1
    assert group.playback_state == PlayBackState.PLAYBACK_STATE_PLAYING


async def test_nothing_is_read_once_an_event_reports_playing() -> None:
    """A player that sends its event in time is not asked for its status."""
    group, read = _group()

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    group._handle_playback_status_update(_status("PLAYING"))
    await _followed(group)

    read.assert_not_awaited()


async def test_a_read_that_fails_is_tried_again() -> None:
    """A player that refuses or does not answer a read is asked again."""
    group, read = _group(
        FailedCommand("ERROR_COMMAND_FAILED"),
        CommandTimeout("playback:getPlaybackStatus", 10),
        _status("PLAYING"),
    )

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    await _followed(group)

    assert read.await_count == 3
    assert group.playback_state == PlayBackState.PLAYBACK_STATE_PLAYING


async def test_a_lost_connection_ends_it() -> None:
    """Nothing more is read once the connection is gone."""
    group, read = _group(InvalidState("Not connected"), _status("PLAYING"))

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    await _followed(group)

    assert read.await_count == 1


async def test_a_load_that_never_plays_is_given_up() -> None:
    """The status is read a limited number of times."""
    group, read = _group(*[_status("IDLE", item_id=None)] * 4)

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    await _followed(group)

    assert read.await_count == 4
    assert group.playback_state == PlayBackState.PLAYBACK_STATE_IDLE


async def test_a_refused_load_is_not_followed() -> None:
    """A load the player refuses is not followed."""
    group, read = _group()
    group.client.api.playback_session.load_cloud_queue.side_effect = FailedCommand("ERROR_X")

    with pytest.raises(FailedCommand):
        await group.play_cloud_queue("https://queue", item_id=ITEM)

    assert group._load_follower is None
    read.assert_not_awaited()


async def test_a_stop_ends_it() -> None:
    """The status is not read for a load that was stopped."""
    group, read = _group()

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    await group.stop()
    await _followed(group)

    read.assert_not_awaited()


async def test_a_reply_after_a_stop_is_not_used() -> None:
    """A status read while the group was stopped does not set it playing again."""
    group, read = _group()
    reply: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    reading = asyncio.Event()

    async def _read(_group_id: str) -> dict[str, Any]:
        reading.set()
        return await reply

    read.side_effect = _read
    await group.play_cloud_queue("https://queue", item_id=ITEM)
    async with asyncio.timeout(2):
        await reading.wait()
    await group.stop()
    reply.set_result(_status("PLAYING"))
    await _followed(group)

    assert group.playback_state == PlayBackState.PLAYBACK_STATE_IDLE


async def test_a_new_load_replaces_it() -> None:
    """Only the load made last is followed."""
    group, read = _group(_status("PLAYING", item_id="item2@101"))

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    first = group._load_follower
    await group.play_cloud_queue("https://queue", item_id="item2@101")
    await _followed(group)

    assert first is not None
    assert first.cancelled()
    assert read.await_count == 1


async def test_a_cleanup_ends_it() -> None:
    """A group that is cleaned up (gone, moved or on a new connection) follows no load."""
    group, read = _group()

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    follower = group._load_follower
    group.cleanup()
    assert follower is not None
    await asyncio.wait([follower])

    assert follower.cancelled()
    assert group._load_follower is None
    read.assert_not_awaited()


async def test_the_item_of_before_the_load_is_forgotten() -> None:
    """Metadata held back with the events does not name the previous item as the one that plays."""
    group, _ = _group(_status("PLAYING"))
    container = {"id": {"serviceId": "mass", "objectId": "mass:queue"}}
    group._playback_metadata_data = {
        "container": container,
        "currentItem": {"id": "item0@99"},
        "nextItem": {"id": ITEM},
    }

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    await _followed(group)

    assert group.playback_metadata == {"container": container}


@pytest.mark.parametrize("item_id", [ITEM, None])
async def test_metadata_that_is_not_stale_is_kept(item_id: str | None) -> None:
    """Metadata stays when it names the item that plays, or the status names none."""
    group, _ = _group(_status("PLAYING", item_id=item_id))
    metadata = {"currentItem": {"id": ITEM}}
    group._playback_metadata_data = metadata

    await group.play_cloud_queue("https://queue", item_id=ITEM)
    await _followed(group)

    assert group.playback_metadata is metadata
