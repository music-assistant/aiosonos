"""Tests for playback session events, audio clip status and coordinator changes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from aiosonos.api.models import GroupStatus
from aiosonos.client import SonosLocalApiClient
from aiosonos.const import EventType
from aiosonos.exceptions import FailedCommand
from aiosonos.group import SonosGroup
from aiosonos.player import SonosPlayer

PLAYER = "RINCON_F0F6C1CC8D0401400"
EVICTED = {"errorCode": "ERROR_SESSION_EVICTED", "reason": "Another user joined the session."}


def _client() -> SonosLocalApiClient:
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._player_id = PLAYER
    client._loop = asyncio.get_running_loop()
    client.signal_event = MagicMock()
    client.api = MagicMock()
    client.api.playback_session.create_session = AsyncMock(
        side_effect=[{"sessionId": "session1"}, {"sessionId": "session2"}],
    )
    client.api.playback_session.subscribe = AsyncMock(side_effect=lambda *_: Mock())
    return client


def _group(client: SonosLocalApiClient) -> SonosGroup:
    return SonosGroup(client, {"id": "group1", "coordinatorId": PLAYER, "playerIds": [PLAYER]})


def _session_error_callback(client: SonosLocalApiClient, index: int = -1) -> Mock:
    return client.api.playback_session.subscribe.await_args_list[index].args[2]


async def test_eviction_clears_the_active_session_and_is_signalled() -> None:
    """ERROR_SESSION_EVICTED for the active session drops it and signals SESSION_ERROR."""
    client = _client()
    group = _group(client)
    await group.create_playback_session()

    _session_error_callback(client)(EVICTED)

    assert group.active_session_id is None
    event = client.signal_event.call_args.args[0]
    assert event.event_type == EventType.SESSION_ERROR
    assert event.object_id == "group1"
    assert event.data == {**EVICTED, "sessionId": "session1"}


async def test_error_for_a_replaced_session_is_ignored() -> None:
    """A late error for a session the group replaced changes nothing and is not signalled."""
    client = _client()
    group = _group(client)
    await group.create_playback_session()
    first_listener = client.api.playback_session.subscribe.await_args_list[0]
    await group.create_playback_session()

    first_listener.args[2](EVICTED)

    assert group.active_session_id == "session2"
    client.signal_event.assert_not_called()


async def test_new_session_unsubscribes_the_previous_one() -> None:
    """The old session's subscription ends once the new session exists."""
    client = _client()
    unsubscribes = [Mock(), Mock()]
    client.api.playback_session.subscribe = AsyncMock(side_effect=unsubscribes)
    group = _group(client)

    await group.create_playback_session()
    await group.create_playback_session()

    unsubscribes[0].assert_called_once()
    unsubscribes[1].assert_not_called()
    group.cleanup()
    unsubscribes[1].assert_called_once()


async def test_eviction_caused_by_a_replacement_is_not_signalled() -> None:
    """The new session evicts the old one; that eviction is not reported as an error."""
    client = _client()
    group = _group(client)
    await group.create_playback_session()
    first_error_callback = _session_error_callback(client)

    def _create(*_: object) -> dict[str, str]:
        first_error_callback(EVICTED)
        return {"sessionId": "session2"}

    client.api.playback_session.create_session.side_effect = _create
    await group.create_playback_session()

    assert group.active_session_id == "session2"
    client.signal_event.assert_not_called()


async def test_refused_replacement_keeps_watching_the_old_session() -> None:
    """When the new session is refused, the old one stays monitored for evictions."""
    client = _client()
    unsubscribes = [Mock(), Mock()]
    client.api.playback_session.subscribe = AsyncMock(side_effect=unsubscribes)
    group = _group(client)
    await group.create_playback_session()
    client.api.playback_session.create_session.side_effect = FailedCommand(
        "ERROR_SESSION_IN_PROGRESS"
    )

    with pytest.raises(FailedCommand):
        await group.create_playback_session()
    _session_error_callback(client, 0)(EVICTED)

    unsubscribes[0].assert_not_called()
    assert group.active_session_id is None
    assert client.signal_event.call_args.args[0].event_type == EventType.SESSION_ERROR


async def test_eviction_during_a_refused_replacement_still_counts() -> None:
    """An eviction held back while a replacement was tried is handled when it fails."""
    client = _client()
    group = _group(client)
    await group.create_playback_session()
    first_error_callback = _session_error_callback(client)

    def _create(*_: object) -> dict[str, str]:
        first_error_callback(EVICTED)
        raise FailedCommand("ERROR_SESSION_IN_PROGRESS")

    client.api.playback_session.create_session.side_effect = _create
    with pytest.raises(FailedCommand):
        await group.create_playback_session()

    assert group.active_session_id is None
    assert client.signal_event.call_args.args[0].data["sessionId"] == "session1"


async def test_cleanup_during_a_pending_subscription_undoes_it() -> None:
    """A subscription that completes after the group was cleaned up is unsubscribed at once."""
    client = _client()
    unsubscribe = Mock()
    group = _group(client)

    async def _subscribe(*_: object) -> Mock:
        group.cleanup()
        return unsubscribe

    client.api.playback_session.subscribe = _subscribe
    await group.create_playback_session()

    unsubscribe.assert_called_once()
    assert group._unsubscribe_session is None


async def test_cleanup_while_the_session_is_created_skips_the_subscription() -> None:
    """A group cleaned up during createSession does not subscribe to the new session."""
    client = _client()
    group = _group(client)

    def _create(*_: object) -> dict[str, str]:
        group.cleanup()
        return {"sessionId": "session1"}

    client.api.playback_session.create_session.side_effect = _create
    await group.create_playback_session()

    client.api.playback_session.subscribe.assert_not_awaited()


async def test_refused_session_subscription_keeps_the_session() -> None:
    """A session the player will not let us subscribe to is still used."""
    client = _client()
    client.api.playback_session.subscribe = AsyncMock(
        side_effect=FailedCommand("ERROR_UNSUPPORTED_COMMAND"),
    )
    group = _group(client)

    session = await group.create_playback_session()

    assert session == {"sessionId": "session1"}
    assert group.active_session_id == "session1"


def _player(client: SonosLocalApiClient) -> SonosPlayer:
    return SonosPlayer(client, {"id": PLAYER, "name": "Office"})


def _clip(status: str) -> dict[str, str]:
    # as the Era 300 sent it for a chime loaded with name/appId/volume only
    return {
        "_objectType": "audioClip",
        "id": "05edf9d0-591a-494a-8045-f5f01295a3ce",
        "name": "validate",
        "appId": "com.aiosonos.validate",
        "priority": "LOW",
        "clipType": "CHIME",
        "status": status,
        "clipLEDBehavior": "NONE",
    }


async def test_play_audio_clip_returns_the_clip_and_subscribes_once() -> None:
    """The loaded clip is returned; audioClip is subscribed to before the first clip only."""
    client = _client()
    client.api.audio_clip.subscribe = AsyncMock()
    client.api.audio_clip.load_audio_clip = AsyncMock(return_value=_clip("ACTIVE"))
    player = _player(client)

    clip = await player.play_audio_clip("http://host/chime.mp3")
    await player.play_audio_clip("http://host/chime.mp3")

    assert clip == _clip("ACTIVE")
    client.api.audio_clip.subscribe.assert_awaited_once_with(
        PLAYER, player._handle_audio_clip_status
    )


async def test_refused_clip_subscription_still_plays_the_clip() -> None:
    """A refused audioClip subscription does not stop the clip and is tried again next time."""
    client = _client()
    client.api.audio_clip.subscribe = AsyncMock(side_effect=FailedCommand("ERROR"))
    client.api.audio_clip.load_audio_clip = AsyncMock(return_value=_clip("ACTIVE"))
    player = _player(client)

    await player.play_audio_clip("http://host/chime.mp3")
    await player.play_audio_clip("http://host/chime.mp3")

    assert client.api.audio_clip.load_audio_clip.await_count == 2
    assert client.api.audio_clip.subscribe.await_count == 2


async def test_audio_clip_status_follows_the_recorded_events() -> None:
    """The three recorded audioClipStatus events: none, ACTIVE, DONE; each is signalled."""
    client = _client()
    player = _player(client)
    clip_id = _clip("ACTIVE")["id"]

    for clips in ([], [_clip("ACTIVE")], [_clip("DONE")]):
        player._handle_audio_clip_status({"_objectType": "audioClipStatus", "audioClips": clips})

    assert player.audio_clip_status(clip_id) == "DONE"
    assert player.audio_clip_status("unknown") is None
    events = [call.args[0] for call in client.signal_event.call_args_list]
    assert [event.event_type for event in events] == [EventType.AUDIO_CLIP_STATUS] * 3
    assert events[-1].object_id == PLAYER


async def test_clip_status_reflects_the_last_event_only() -> None:
    """A clip the player no longer lists has no known status."""
    client = _client()
    player = _player(client)
    clip_id = _clip("DONE")["id"]
    player._handle_audio_clip_status({"audioClips": [_clip("DONE")]})

    player._handle_audio_clip_status({"audioClips": []})

    assert player.audio_clip_status(clip_id) is None


async def test_client_signals_coordinator_change_for_any_group() -> None:
    """A move is signalled with its group id, also for a group this client does not track."""
    client = _client()
    moved = {
        "_objectType": "groupCoordinatorChanged",
        "groupStatus": "GROUP_STATUS_MOVED",
        "groupName": "Bathroom + 1",
        "websocketUrl": "wss://192.168.113.18:1443/websocket/api",
        "playerId": "RINCON_48A6B86DD3F101400",
    }

    client._handle_group_coordinator_changed("RINCON_F0F6C1CC8D0401400:140007645", moved)

    event = client.signal_event.call_args.args[0]
    assert event.event_type == EventType.GROUP_COORDINATOR_CHANGED
    assert event.object_id == "RINCON_F0F6C1CC8D0401400:140007645"
    assert event.data["groupStatus"] == GroupStatus.MOVED
    assert event.data["playerId"] == "RINCON_48A6B86DD3F101400"


async def test_clips_played_together_subscribe_once() -> None:
    """Two clips started at the same time share one audioClip subscription."""
    client = _client()
    subscribed = asyncio.Event()

    async def _subscribe(*_: object) -> None:
        await subscribed.wait()

    client.api.audio_clip.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.audio_clip.load_audio_clip = AsyncMock(return_value=_clip("ACTIVE"))
    player = _player(client)

    first = asyncio.ensure_future(player.play_audio_clip("http://host/a.mp3"))
    second = asyncio.ensure_future(player.play_audio_clip("http://host/b.mp3"))
    await asyncio.sleep(0)
    subscribed.set()
    await asyncio.gather(first, second)

    client.api.audio_clip.subscribe.assert_awaited_once()


async def test_refused_concurrent_replacement_keeps_the_first_session_monitored() -> None:
    """A second session refused while the first one subscribes leaves the first one watched."""
    client = _client()
    subscribed = asyncio.Event()
    unsubscribe = Mock()

    async def _subscribe(*_: object) -> Mock:
        await subscribed.wait()
        return unsubscribe

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.create_session = AsyncMock(
        side_effect=[{"sessionId": "session1"}, FailedCommand("ERROR_SESSION_IN_PROGRESS")],
    )
    group = _group(client)

    first = asyncio.ensure_future(group.create_playback_session())
    await asyncio.sleep(0)
    with pytest.raises(FailedCommand):
        await group.create_playback_session()
    subscribed.set()
    await first

    unsubscribe.assert_not_called()
    assert group._unsubscribe_session is unsubscribe
    _session_error_callback(client, 0)(EVICTED)
    assert group.active_session_id is None


async def test_overlapping_replacements_do_not_report_a_takeover() -> None:
    """Two replacements asked for together: the first failing does not expose the second's."""
    client = _client()
    group = _group(client)
    await group.create_playback_session()
    first_error_callback = _session_error_callback(client)
    first_create, second_create = asyncio.Event(), asyncio.Event()
    second_create_started = asyncio.Event()
    creations = 0

    async def _create(*_: object) -> dict[str, str]:
        nonlocal creations
        creations += 1
        if creations == 1:
            await first_create.wait()
            raise FailedCommand("ERROR_SESSION_IN_PROGRESS")
        second_create_started.set()
        await second_create.wait()
        return {"sessionId": "session2"}

    client.api.playback_session.create_session = AsyncMock(side_effect=_create)
    first = asyncio.ensure_future(group.create_playback_session())
    second = asyncio.ensure_future(group.create_playback_session())
    await asyncio.sleep(0)
    first_create.set()
    with pytest.raises(FailedCommand):
        await first
    # the speaker evicts session1 for session2 while that creation is still unanswered
    await second_create_started.wait()
    first_error_callback(EVICTED)
    second_create.set()
    await second

    assert group.active_session_id == "session2"
    client.signal_event.assert_not_called()


async def test_a_clip_played_meanwhile_waits_for_the_subscription() -> None:
    """No clip is loaded before the audioClip subscription is in place."""
    client = _client()
    subscribed = asyncio.Event()

    async def _subscribe(*_: object) -> None:
        await subscribed.wait()

    client.api.audio_clip.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.audio_clip.load_audio_clip = AsyncMock(return_value=_clip("ACTIVE"))
    player = _player(client)

    first = asyncio.ensure_future(player.play_audio_clip("http://host/a.mp3"))
    second = asyncio.ensure_future(player.play_audio_clip("http://host/b.mp3"))
    await asyncio.sleep(0.01)
    client.api.audio_clip.load_audio_clip.assert_not_awaited()
    subscribed.set()
    await asyncio.gather(first, second)

    assert client.api.audio_clip.load_audio_clip.await_count == 2


async def test_a_cancelled_clip_subscription_is_tried_again() -> None:
    """A subscription cut short leaves the player unsubscribed, so the next clip subscribes."""
    client = _client()
    never = asyncio.Event()

    async def _subscribe(*_: object) -> None:
        await never.wait()

    client.api.audio_clip.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.audio_clip.load_audio_clip = AsyncMock(return_value=_clip("ACTIVE"))
    player = _player(client)

    attempt = asyncio.ensure_future(player.play_audio_clip("http://host/a.mp3"))
    await asyncio.sleep(0)
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt
    client.api.audio_clip.subscribe = AsyncMock()
    await player.play_audio_clip("http://host/a.mp3")

    client.api.audio_clip.subscribe.assert_awaited_once()
