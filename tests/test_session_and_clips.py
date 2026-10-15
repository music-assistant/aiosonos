"""Tests for playback session events, audio clip status and coordinator changes."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from aiosonos.api.models import GroupStatus
from aiosonos.client import SonosLocalApiClient
from aiosonos.const import EventType
from aiosonos.exceptions import CommandTimeout, FailedCommand, InvalidState
from aiosonos.group import SonosGroup
from aiosonos.player import SonosPlayer

if TYPE_CHECKING:
    from collections.abc import Callable

    from aiosonos.api.models import Container

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
    unsubscribes[0].assert_not_called()
    _session_error_callback(client, 0)(EVICTED)

    assert group.active_session_id is None
    assert client.signal_event.call_args.args[0].event_type == EventType.SESSION_ERROR
    unsubscribes[0].assert_called_once()


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
    with pytest.raises(InvalidState):
        await group.create_playback_session()

    unsubscribe.assert_called_once()
    assert group._unsubscribe_session is None
    assert group.active_session_id is None


async def test_cleanup_while_the_session_is_created_hands_it_out_to_nobody() -> None:
    """A group cleaned up during createSession neither subscribes to nor returns the session."""
    client = _client()
    group = _group(client)

    def _create(*_: object) -> dict[str, str]:
        group.cleanup()
        return {"sessionId": "session1"}

    client.api.playback_session.create_session.side_effect = _create
    with pytest.raises(InvalidState):
        await group.create_playback_session()

    client.api.playback_session.subscribe.assert_not_awaited()
    assert group.active_session_id is None


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


async def test_a_new_connection_subscribes_to_audio_clips_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """connect() forgets the clip subscription made on the connection it replaces."""
    client = _client()
    client.api.audio_clip.subscribe = AsyncMock()
    client.api.audio_clip.load_audio_clip = AsyncMock(return_value=_clip("ACTIVE"))
    player = _player(client)
    client._player = player
    await player.play_audio_clip("http://host/chime.mp3")
    player._handle_audio_clip_status({"audioClips": [_clip("ACTIVE")]})  # type: ignore[typeddict-item]
    discovery = {"playerId": PLAYER, "householdId": "household1", "websocketUrl": "wss://host"}
    monkeypatch.setattr("aiosonos.client.get_discovery_info", AsyncMock(return_value=discovery))
    new_api = MagicMock()
    new_api.connect = AsyncMock()
    new_api.audio_clip.subscribe = AsyncMock()
    new_api.audio_clip.load_audio_clip = AsyncMock(return_value=_clip("ACTIVE"))
    monkeypatch.setattr("aiosonos.client.SonosLocalWebSocketsApi", MagicMock(return_value=new_api))

    await client.connect()
    assert player.audio_clip_status(_clip("ACTIVE")["id"]) is None
    await player.play_audio_clip("http://host/chime.mp3")

    new_api.audio_clip.subscribe.assert_awaited_once_with(PLAYER, player._handle_audio_clip_status)


@pytest.mark.parametrize(
    "outcome",
    [None, FailedCommand("ERROR_UNSUPPORTED_COMMAND"), CommandTimeout("audioClip:subscribe", 10)],
    ids=["subscribed", "refused", "unanswered"],
)
async def test_a_connection_replaced_while_subscribing_to_clips_is_subscribed_to(
    outcome: FailedCommand | None,
) -> None:
    """A clip whose subscribe ends on a replaced connection subscribes on the new one first."""
    client = _client()
    subscribed = asyncio.Event()
    order: list[str] = []

    async def _old_subscribe(*_: object) -> None:
        await subscribed.wait()
        if outcome is not None:
            raise outcome

    async def _new_subscribe(*_: object) -> None:
        order.append("subscribe new")

    async def _new_load(*_: object, **__: object) -> dict[str, str]:
        order.append("load new")
        return _clip("ACTIVE")

    old_api = client.api
    old_api.audio_clip.subscribe = AsyncMock(side_effect=_old_subscribe)
    old_api.audio_clip.load_audio_clip = AsyncMock(return_value=_clip("ACTIVE"))
    new_api = MagicMock()
    new_api.audio_clip.subscribe = AsyncMock(side_effect=_new_subscribe)
    new_api.audio_clip.load_audio_clip = AsyncMock(side_effect=_new_load)
    player = _player(client)

    clip = asyncio.ensure_future(player.play_audio_clip("http://host/a.mp3"))
    await asyncio.sleep(0.01)
    client.api = new_api  # as connect() does, with the player's cleanup
    player.cleanup()
    subscribed.set()
    await clip

    assert order == ["subscribe new", "load new"]
    new_api.audio_clip.subscribe.assert_awaited_once_with(PLAYER, player._handle_audio_clip_status)
    old_api.audio_clip.load_audio_clip.assert_not_awaited()
    await player.play_audio_clip("http://host/b.mp3")
    new_api.audio_clip.subscribe.assert_awaited_once()


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
    """A second session asked for while the first one subscribes waits; refused, nothing changes."""
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
    second = asyncio.ensure_future(group.create_playback_session())
    await asyncio.sleep(0.01)
    assert client.api.playback_session.create_session.await_count == 1
    subscribed.set()
    await first
    with pytest.raises(FailedCommand):
        await second

    unsubscribe.assert_not_called()
    assert group._unsubscribe_session is unsubscribe
    _session_error_callback(client, 0)(EVICTED)
    assert group.active_session_id is None


async def test_the_same_session_handed_back_again_keeps_its_subscription() -> None:
    """A creation answered with the session in use subscribes and unsubscribes nothing."""
    client = _client()
    listeners: dict[str, object] = {}

    async def _subscribe(session_id: str, callback: object, *_: object) -> Callable[[], None]:
        # as the namespace does: one listener per session id, gone on unsubscribe
        await asyncio.sleep(0)
        listeners[session_id] = callback
        return lambda: listeners.pop(session_id)

    client.api.playback_session.create_session = AsyncMock(return_value={"sessionId": "session1"})
    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    group = _group(client)

    await asyncio.gather(group.create_playback_session(), group.create_playback_session())

    client.api.playback_session.subscribe.assert_awaited_once()
    assert list(listeners) == ["session1"]
    assert group.active_session_id == "session1"
    group.cleanup()
    assert listeners == {}


async def test_an_eviction_before_the_same_session_is_handed_back_counts() -> None:
    """Evicted while asking for a session, and given the same one back: it is gone, not revived."""
    client = _client()
    group = _group(client)
    await group.create_playback_session()
    first_error_callback = _session_error_callback(client)

    def _create(*_: object) -> dict[str, str]:
        first_error_callback(EVICTED)
        return {"sessionId": "session1"}

    client.api.playback_session.create_session.side_effect = _create
    with pytest.raises(FailedCommand) as excinfo:
        await group.create_playback_session()

    assert excinfo.value.error_code == "ERROR_SESSION_EVICTED"
    assert group.active_session_id is None
    assert client.signal_event.call_args.args[0].data["sessionId"] == "session1"
    client.api.playback_session.subscribe.assert_awaited_once()


async def test_the_same_session_handed_back_unmonitored_is_subscribed_to() -> None:
    """A session whose subscription was refused is subscribed to when handed back again."""
    client = _client()
    unsubscribe = Mock()
    client.api.playback_session.subscribe = AsyncMock(
        side_effect=[FailedCommand("ERROR_UNSUPPORTED_COMMAND"), unsubscribe],
    )
    client.api.playback_session.create_session = AsyncMock(return_value={"sessionId": "session1"})
    group = _group(client)
    await group.create_playback_session()
    assert group._unsubscribe_session is None

    await group.create_playback_session()

    assert client.api.playback_session.subscribe.await_count == 2
    assert group._unsubscribe_session is unsubscribe
    assert group.active_session_id == "session1"


def _commands(client: SonosLocalApiClient) -> list[str]:
    """Record the session commands as they go out: subscribe <id>, unsubscribe <id>."""
    commands: list[str] = []

    async def _subscribe(session_id: str, *_: object) -> Callable[[], None]:
        commands.append(f"subscribe {session_id}")
        return lambda: commands.append(f"unsubscribe {session_id}")

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.suspend = AsyncMock()
    return commands


async def test_a_stopped_session_handed_back_again_is_still_listened_to() -> None:
    """After a stop, the same session created again keeps its subscription: no commands."""
    client = _client()
    commands = _commands(client)
    client.api.playback_session.create_session = AsyncMock(return_value={"sessionId": "session1"})
    group = _group(client)
    await group.create_playback_session()
    await group.stop()
    assert group.active_session_id is None

    await group.create_playback_session()

    assert commands == ["subscribe session1"]
    assert group.active_session_id == "session1"
    _session_error_callback(client)(EVICTED)
    assert group.active_session_id is None


async def test_a_new_session_after_a_stop_replaces_the_stopped_ones_listener() -> None:
    """A different session after a stop ends the stopped one's subscription before its own."""
    client = _client()
    commands = _commands(client)
    group = _group(client)
    await group.create_playback_session()
    await group.stop()

    await group.create_playback_session()

    assert commands == ["subscribe session1", "unsubscribe session1", "subscribe session2"]
    assert group.active_session_id == "session2"
    assert group._subscribed_session_id == "session2"


async def test_an_eviction_while_subscribing_is_not_lost() -> None:
    """An eviction delivered before the subscribe reply ends the session; the next one is new."""
    client = _client()
    commands = _commands(client)
    subscribe = client.api.playback_session.subscribe.side_effect

    async def _subscribe(session_id: str, callback: object, error_callback: object) -> object:
        if session_id == "session1":
            error_callback(EVICTED)  # type: ignore[operator]
        return await subscribe(session_id, callback, error_callback)

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    group = _group(client)

    with pytest.raises(FailedCommand) as excinfo:
        await group.create_playback_session()

    assert excinfo.value.error_code == "ERROR_SESSION_EVICTED"
    assert group.active_session_id is None
    assert client.signal_event.call_args.args[0].data["sessionId"] == "session1"
    await group.create_playback_session()
    assert group.active_session_id == "session2"
    assert commands == ["subscribe session1", "unsubscribe session1", "subscribe session2"]


async def test_a_stopped_session_evicted_before_it_is_handed_back_is_not_revived() -> None:
    """An eviction of the stopped session during createSession makes its id unusable."""
    client = _client()
    commands = _commands(client)
    group = _group(client)
    await group.create_playback_session()
    first_error_callback = _session_error_callback(client)
    await group.stop()

    def _create(*_: object) -> dict[str, str]:
        first_error_callback(EVICTED)
        return {"sessionId": "session1"}

    client.api.playback_session.create_session.side_effect = _create
    with pytest.raises(FailedCommand):
        await group.create_playback_session()

    assert group.active_session_id is None
    assert group._subscribed_session_id is None
    assert commands == ["subscribe session1", "unsubscribe session1"]
    client.signal_event.assert_not_called()


async def test_an_eviction_of_a_stopped_session_ends_its_subscription() -> None:
    """A stopped session evicted by someone else is not listened to any longer."""
    client = _client()
    commands = _commands(client)
    group = _group(client)
    await group.create_playback_session()
    await group.stop()

    _session_error_callback(client)(EVICTED)

    assert commands == ["subscribe session1", "unsubscribe session1"]
    assert group._subscribed_session_id is None
    client.signal_event.assert_not_called()


async def test_an_error_after_cleanup_before_the_subscribe_reply_is_ignored() -> None:
    """A session error for a group cleaned up while subscribing is not signalled."""
    client = _client()
    unsubscribe = Mock()
    group = _group(client)

    async def _subscribe(_session_id: str, _callback: object, error_callback: object) -> Mock:
        group.cleanup()
        error_callback(EVICTED)  # type: ignore[operator]
        return unsubscribe

    client.api.playback_session.subscribe = _subscribe
    with pytest.raises(InvalidState):
        await group.create_playback_session()

    client.signal_event.assert_not_called()
    unsubscribe.assert_called_once()


async def test_a_stop_ordered_while_subscribing_lands_after_it() -> None:
    """A stop ordered before the subscribe reply waits for it; the session stays listened to."""
    client = _client()
    commands = _commands(client)
    subscribed = asyncio.Event()
    subscribe = client.api.playback_session.subscribe.side_effect
    group = _group(client)

    async def _subscribe(*args: object) -> object:
        await subscribed.wait()
        return await subscribe(*args)

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    creation = asyncio.ensure_future(group.create_playback_session())
    stop = asyncio.ensure_future(group.stop())
    await asyncio.sleep(0.01)
    client.api.playback_session.suspend.assert_not_awaited()
    subscribed.set()
    await asyncio.gather(creation, stop)

    client.api.playback_session.suspend.assert_awaited_once_with("session1")
    assert group.active_session_id is None
    assert group._subscribed_session_id == "session1"
    assert commands == ["subscribe session1"]


async def test_a_stop_ordered_during_a_play_lands_after_its_load() -> None:
    """A stop ordered while a queue is being started stops that queue, not an earlier state."""
    client = _client()
    _commands(client)
    subscribed = asyncio.Event()
    order: list[str] = []

    async def _subscribe(*_: object) -> Mock:
        await subscribed.wait()
        return Mock()

    async def _load(session_id: str, **_: object) -> None:
        order.append(f"load {session_id}")

    async def _suspend(session_id: str) -> None:
        order.append(f"suspend {session_id}")

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.load_cloud_queue = AsyncMock(side_effect=_load)
    client.api.playback_session.suspend = AsyncMock(side_effect=_suspend)
    group = _group(client)

    play = asyncio.ensure_future(group.play_cloud_queue("http://host/queue/"))
    stop = asyncio.ensure_future(group.stop())
    await asyncio.sleep(0.01)
    subscribed.set()
    await asyncio.gather(play, stop)

    assert order == ["load session1", "suspend session1"]
    assert group.active_session_id is None


async def test_an_unanswered_session_subscribe_is_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A subscribe the speaker never answers leaves the session in use, and is logged."""
    client = _client()
    client.api.playback_session.subscribe = AsyncMock(
        side_effect=CommandTimeout("playbackSession:subscribe", 10),
    )
    group = _group(client)

    with caplog.at_level(logging.WARNING):
        session = await group.create_playback_session()

    assert session == {"sessionId": "session1"}
    assert group.active_session_id == "session1"
    assert group._subscribed_session_id is None
    assert "No reply subscribing to session session1" in caplog.text


async def test_a_new_connection_undoes_the_groups_subscriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """connect() drops the subscriptions made on the connection it replaces."""
    client = _client()
    commands = _commands(client)
    client.api.playback_session.create_session = AsyncMock(return_value={"sessionId": "session1"})
    group = _group(client)
    client._groups[group.id] = group
    await group.create_playback_session()
    discovery = {"playerId": PLAYER, "householdId": "household1", "websocketUrl": "wss://host"}
    monkeypatch.setattr("aiosonos.client.get_discovery_info", AsyncMock(return_value=discovery))
    new_api = MagicMock()
    new_api.connect = AsyncMock()
    monkeypatch.setattr("aiosonos.client.SonosLocalWebSocketsApi", MagicMock(return_value=new_api))

    await client.connect()

    assert commands == ["subscribe session1", "unsubscribe session1"]
    assert group._subscribed_session_id is None
    assert group.active_session_id is None
    # the speaker hands the same session back on the new connection: listened to again there
    new_api.playback_session.create_session = AsyncMock(return_value={"sessionId": "session1"})
    new_api.playback_session.subscribe = AsyncMock(return_value=Mock())
    await group.create_playback_session()
    new_api.playback_session.subscribe.assert_awaited_once()
    assert group._subscribed_session_id == "session1"


@pytest.mark.parametrize(
    "failure",
    [FailedCommand("ERROR_COMMAND_FAILED"), InvalidState("Not connected")],
    ids=["refused", "disconnected"],
)
async def test_a_failed_status_setup_keeps_the_session_subscription(failure: Exception) -> None:
    """A group setup that fails (and is retried) undoes its own subscriptions only."""
    client = _client()
    commands = _commands(client)
    group = _group(client)
    await group.create_playback_session()
    client.api.group_volume.get_volume = AsyncMock(side_effect=failure)

    with pytest.raises(type(failure)):
        await group.async_init()

    assert commands == ["subscribe session1"]
    assert group._subscribed_session_id == "session1"


async def test_a_cleanup_before_a_waiting_creation_starts_does_not_count_against_it() -> None:
    """A creation that waited its turn subscribes, whatever happened to the group before."""
    client = _client()
    subscribed = asyncio.Event()

    async def _subscribe(session_id: str, *_: object) -> Mock:
        if session_id == "session1":
            await subscribed.wait()
        return Mock()

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    group = _group(client)
    first = asyncio.ensure_future(group.create_playback_session())
    second = asyncio.ensure_future(group.create_playback_session())
    await asyncio.sleep(0.01)
    group.cleanup()  # the group moved away and back while the first one subscribed
    subscribed.set()
    with pytest.raises(InvalidState):
        await first
    await second

    assert client.api.playback_session.subscribe.await_count == 2
    assert group._subscribed_session_id == "session2"


async def test_a_stream_is_not_loaded_into_a_session_evicted_while_subscribing() -> None:
    """play_stream_url sends no load when its session was evicted before the subscribe reply."""
    client = _client()

    async def _subscribe(_session_id: str, _callback: object, error_callback: object) -> Mock:
        error_callback(EVICTED)  # type: ignore[operator]
        return Mock()

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.load_stream_url = AsyncMock()
    group = _group(client)

    with pytest.raises(FailedCommand):
        await group.play_stream_url("http://host/a", cast("Container", {}))

    client.api.playback_session.load_stream_url.assert_not_awaited()


@pytest.mark.parametrize(
    "refusal",
    [FailedCommand("ERROR_UNSUPPORTED_COMMAND"), CommandTimeout("playbackSession:subscribe", 10)],
    ids=["refused", "unanswered"],
)
async def test_a_stream_is_not_loaded_after_an_eviction_even_if_the_subscribe_fails(
    refusal: FailedCommand,
) -> None:
    """An eviction during a subscribe that then fails still withholds the session."""
    client = _client()

    async def _subscribe(_session_id: str, _callback: object, error_callback: object) -> Mock:
        error_callback(EVICTED)  # type: ignore[operator]
        raise refusal

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.load_stream_url = AsyncMock()
    group = _group(client)

    with pytest.raises(FailedCommand) as excinfo:
        await group.play_stream_url("http://host/a", cast("Container", {}))

    assert excinfo.value.error_code == "ERROR_SESSION_EVICTED"
    client.api.playback_session.load_stream_url.assert_not_awaited()
    assert group.active_session_id is None
    assert client.signal_event.call_args.args[0].data["sessionId"] == "session1"


async def test_a_queue_is_not_loaded_into_a_session_of_a_cleaned_up_group() -> None:
    """play_cloud_queue sends no load when its group was cleaned up before the subscribe reply."""
    client = _client()
    group = _group(client)

    async def _subscribe(*_: object) -> Mock:
        group.cleanup()
        return Mock()

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.load_cloud_queue = AsyncMock()

    with pytest.raises(InvalidState):
        await group.play_cloud_queue("http://host/queue/")

    client.api.playback_session.load_cloud_queue.assert_not_awaited()


async def test_a_stream_loads_into_the_session_made_for_it() -> None:
    """A stream whose session is still subscribing is not loaded into a newer session."""
    client = _client()
    subscribed = asyncio.Event()

    async def _subscribe(session_id: str, *_: object) -> Mock:
        if session_id == "session1":
            await subscribed.wait()
        return Mock()

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.load_stream_url = AsyncMock()
    group = _group(client)

    first = asyncio.ensure_future(group.play_stream_url("http://host/a", cast("Container", {})))
    second = asyncio.ensure_future(group.play_stream_url("http://host/b", cast("Container", {})))
    await asyncio.sleep(0.01)
    subscribed.set()
    await asyncio.gather(first, second)

    loads = client.api.playback_session.load_stream_url.await_args_list
    assert [load.args[0] for load in loads] == ["session1", "session2"]
    assert [load.kwargs["stream_url"] for load in loads] == ["http://host/a", "http://host/b"]
    assert group.active_session_id == "session2"


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


async def test_a_cancelled_session_subscription_leaves_no_session_behind() -> None:
    """A creation cut short while subscribing vouches for no session; the next play makes one."""
    client = _client()
    never = asyncio.Event()

    async def _subscribe(*_: object) -> Mock:
        await never.wait()
        return Mock()

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.load_cloud_queue = AsyncMock()
    group = _group(client)

    attempt = asyncio.ensure_future(group.create_playback_session())
    await asyncio.sleep(0.01)
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt
    assert group.active_session_id is None
    client.api.playback_session.subscribe = AsyncMock(side_effect=lambda *_: Mock())
    await group.play_cloud_queue("http://host/queue/")

    assert client.api.playback_session.create_session.await_count == 2
    assert client.api.playback_session.load_cloud_queue.await_args.args[0] == "session2"
    assert group._subscribed_session_id == "session2"


async def test_queues_started_together_load_in_order() -> None:
    """A queue started while the session is subscribing loads after the one that made it."""
    client = _client()
    subscribed = asyncio.Event()

    async def _subscribe(*_: object) -> Mock:
        await subscribed.wait()
        return Mock()

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.load_cloud_queue = AsyncMock()
    group = _group(client)

    first = asyncio.ensure_future(group.play_cloud_queue("http://host/a/"))
    second = asyncio.ensure_future(group.play_cloud_queue("http://host/b/"))
    await asyncio.sleep(0.01)
    client.api.playback_session.load_cloud_queue.assert_not_awaited()
    subscribed.set()
    await asyncio.gather(first, second)

    loads = client.api.playback_session.load_cloud_queue.await_args_list
    assert [load.args[0] for load in loads] == ["session1", "session1"]
    assert [load.kwargs["queue_base_url"] for load in loads] == ["http://host/a/", "http://host/b/"]
    client.api.playback_session.create_session.assert_awaited_once()


async def test_a_queue_started_during_an_evicted_creation_gets_its_own_session() -> None:
    """A queue waiting on a creation that ends evicted is loaded into a session of its own."""
    client = _client()
    subscribed = asyncio.Event()

    async def _subscribe(session_id: str, _callback: object, error_callback: object) -> Mock:
        if session_id == "session1":
            await subscribed.wait()
            error_callback(EVICTED)  # type: ignore[operator]
        return Mock()

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    client.api.playback_session.load_cloud_queue = AsyncMock()
    group = _group(client)

    first = asyncio.ensure_future(group.play_cloud_queue("http://host/a/"))
    second = asyncio.ensure_future(group.play_cloud_queue("http://host/b/"))
    await asyncio.sleep(0.01)
    subscribed.set()
    with pytest.raises(FailedCommand):
        await first
    await second

    loads = client.api.playback_session.load_cloud_queue.await_args_list
    assert [(load.args[0], load.kwargs["queue_base_url"]) for load in loads] == [
        ("session2", "http://host/b/"),
    ]
    assert group.active_session_id == "session2"


async def test_a_cleanup_after_a_deferred_eviction_is_moot() -> None:
    """An eviction held back during createSession is dropped when the group is cleaned up."""
    client = _client()
    group = _group(client)
    await group.create_playback_session()
    first_error_callback = _session_error_callback(client)
    client.signal_event.reset_mock()

    def _create(*_: object) -> dict[str, str]:
        first_error_callback(EVICTED)
        group.cleanup()
        return {"sessionId": "session1"}

    client.api.playback_session.create_session.side_effect = _create
    with pytest.raises(InvalidState):
        await group.create_playback_session()

    client.signal_event.assert_not_called()
    assert group.active_session_id is None
    assert group._deferred_session_error is None


async def test_a_creation_cancelled_while_unanswered_settles_the_replacement() -> None:
    """A creation cut short before its reply replays the error held back for the old session."""
    client = _client()
    group = _group(client)
    await group.create_playback_session()
    first_error_callback = _session_error_callback(client)
    client.signal_event.reset_mock()
    never = asyncio.Event()

    async def _create(*_: object) -> dict[str, str]:
        await never.wait()
        return {"sessionId": "session2"}

    client.api.playback_session.create_session = AsyncMock(side_effect=_create)
    creation = asyncio.ensure_future(group.create_playback_session())
    await asyncio.sleep(0.01)
    first_error_callback(EVICTED)
    creation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await creation

    assert group._replacing_session_id is None
    assert group._deferred_session_error is None
    assert group.active_session_id is None
    assert client.signal_event.call_args.args[0].data["sessionId"] == "session1"


async def test_a_stop_whose_clear_session_is_cleaned_up_loads_nothing() -> None:
    """The clear-path creation of a stop raises InvalidState past the stop, and loads nothing."""
    client = _client()
    group = _group(client)
    client.api.playback_session.suspend = AsyncMock(side_effect=FailedCommand("ERROR_INVALID"))
    client.api.playback_session.load_stream_url = AsyncMock()

    async def _subscribe(*_: object) -> Mock:
        group.cleanup()
        return Mock()

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    with pytest.raises(InvalidState):
        await group.stop()

    client.api.playback_session.load_stream_url.assert_not_awaited()
    assert group.active_session_id is None


async def test_an_evicted_session_handed_back_again_is_a_live_one() -> None:
    """A session evicted earlier that createSession hands back is used like any other."""
    client = _client()
    client.api.playback_session.create_session = AsyncMock(return_value={"sessionId": "session1"})
    group = _group(client)
    await group.create_playback_session()
    _session_error_callback(client)(EVICTED)
    assert group.active_session_id is None

    session = await group.create_playback_session()

    assert session == {"sessionId": "session1"}
    assert group.active_session_id == "session1"


async def test_a_held_back_error_that_is_no_eviction_does_not_withhold_the_session() -> None:
    """A non-eviction error held back for a session handed back again is replayed only."""
    client = _client()
    client.api.playback_session.create_session = AsyncMock(return_value={"sessionId": "session1"})
    group = _group(client)
    await group.create_playback_session()
    first_error_callback = _session_error_callback(client)
    client.signal_event.reset_mock()
    other_error = {"errorCode": "ERROR_PLAYBACK_FAILED", "reason": "something"}

    def _create(*_: object) -> dict[str, str]:
        first_error_callback(other_error)
        return {"sessionId": "session1"}

    client.api.playback_session.create_session.side_effect = _create
    session = await group.create_playback_session()

    assert session == {"sessionId": "session1"}
    assert group.active_session_id == "session1"
    assert client.signal_event.call_args.args[0].data["errorCode"] == "ERROR_PLAYBACK_FAILED"


async def test_cleanup_tolerates_a_session_unsubscribe_on_a_closed_connection() -> None:
    """Dropping the session listener after the connection closed does not raise."""
    client = _client()
    client.api.playback_session.subscribe = AsyncMock(
        return_value=Mock(side_effect=InvalidState("Not connected"))
    )
    group = _group(client)
    await group.create_playback_session()

    group.cleanup()

    assert group._unsubscribe_session is None


async def test_an_eviction_while_subscribing_on_a_closed_connection_still_counts() -> None:
    """Undoing the subscription on a closed connection does not hide the eviction."""
    client = _client()

    async def _subscribe(_session_id: str, _callback: object, error_callback: object) -> Mock:
        error_callback(EVICTED)  # type: ignore[operator]
        return Mock(side_effect=InvalidState("Not connected"))

    client.api.playback_session.subscribe = AsyncMock(side_effect=_subscribe)
    group = _group(client)

    with pytest.raises(FailedCommand) as excinfo:
        await group.create_playback_session()

    assert excinfo.value.error_code == "ERROR_SESSION_EVICTED"
