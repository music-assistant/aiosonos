"""Tests for routing incoming websocket messages."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, Mock, call

import orjson
import pytest

from aiosonos.api import SonosLocalWebSocketsApi
from aiosonos.exceptions import CommandTimeout, FailedCommand, InvalidState

if TYPE_CHECKING:
    from aiosonos.api.namespaces._base import UnsubscribeCallbackType

GROUP = "group1"


def _api() -> SonosLocalWebSocketsApi:
    api = SonosLocalWebSocketsApi("wss://1.2.3.4:1443/websocket/api", MagicMock())
    api._loop = asyncio.get_running_loop()
    return api


def _answer_commands(api: SonosLocalWebSocketsApi) -> Mock:
    """Let subscribe commands succeed; returns the mock that records unsubscribe commands."""
    api.send_command = AsyncMock()  # type: ignore[method-assign]
    api.send_command_no_wait = Mock()  # type: ignore[method-assign]
    return api.send_command_no_wait


def _hold_replies(api: SonosLocalWebSocketsApi) -> tuple[list[asyncio.Future[None]], Mock]:
    """Hold each subscribe command until its future (in call order) is answered."""
    replies: list[asyncio.Future[None]] = []

    async def _send_command(**_: object) -> None:
        reply: asyncio.Future[None] = api._loop.create_future()
        replies.append(reply)
        await reply

    api.send_command = _send_command  # type: ignore[method-assign]
    api.send_command_no_wait = Mock()  # type: ignore[method-assign]
    return replies, api.send_command_no_wait


async def _subscribe_playback(
    api: SonosLocalWebSocketsApi, **kwargs: Mock
) -> UnsubscribeCallbackType:
    _answer_commands(api)
    return await api.playback.subscribe(GROUP, Mock(), **kwargs)


SESSION_EVICTED = {
    "errorCode": "ERROR_SESSION_EVICTED",
    "reason": "Another user joined the session.",
}
SESSION_SUSPENDED = {"suspended": True}


async def _drain() -> None:
    """Let the tasks created by the message handler run."""
    for _ in range(3):
        await asyncio.sleep(0)


async def test_playback_error_routed_to_error_callback() -> None:
    """An unsolicited playbackError reaches the error callback of its group."""
    api = _api()
    error_callback = Mock()
    await _subscribe_playback(api, error_callback=error_callback)
    error = {"errorCode": "ERROR_PLAYBACK_FAILED", "reason": "stream gone"}

    api._handle_incoming_message(({"type": "playbackError", "groupId": GROUP}, error))
    await _drain()

    error_callback.assert_called_once_with(error)


async def test_command_error_raises_failed_command() -> None:
    """An error answering a command fails that command with FailedCommand."""
    api = _api()
    future = api._loop.create_future()
    api._result_futures["cmd1"] = future

    api._handle_incoming_message(
        ({"cmdId": "cmd1"}, {"errorCode": "ERROR_INVALID_PARAMETER", "reason": "bad"}),
    )

    with pytest.raises(FailedCommand):
        await future


async def test_unknown_error_event_only_logged(caplog: pytest.LogCaptureFixture) -> None:
    """An unsolicited error of another type is logged at debug level only."""
    api = _api()
    error_callback = Mock()
    await _subscribe_playback(api, error_callback=error_callback)

    with caplog.at_level(logging.DEBUG, logger=api.logger.name):
        api._handle_incoming_message(
            ({"type": "groupVolumeError", "groupId": GROUP}, {"errorCode": "ERROR"}),
        )
        await _drain()

    error_callback.assert_not_called()
    assert [record.levelno for record in caplog.records] == [logging.DEBUG]


async def test_playback_subscribe_keeps_error_listener_until_unsubscribed() -> None:
    """An error listener lives as long as its handle is unused; a later subscribe adds its own."""
    api = _api()
    error_callback = Mock()
    error = {"errorCode": "ERROR_PLAYBACK_FAILED", "reason": "no"}
    unsubscribe = await _subscribe_playback(api, error_callback=error_callback)
    api._handle_incoming_message(({"type": "playbackError", "groupId": GROUP}, error))
    await _drain()
    error_callback.assert_called_once_with(error)

    unsubscribe_other = await _subscribe_playback(api)
    unsubscribe()
    api._handle_incoming_message(({"type": "playbackError", "groupId": GROUP}, error))
    await _drain()
    error_callback.assert_called_once_with(error)

    unsubscribe_other()
    assert GROUP not in api.playback._subscriptions


# headers and bodies as an Era 300 (firmware 97.1) sent them
OFFICE_GROUP = "RINCON_F0F6C1CC8D0401400:140007645"
COORDINATOR_UPDATED = (
    {
        "namespace": "global",
        "groupId": OFFICE_GROUP,
        "name": "groupCoordinatorChanged",
        "type": "groupCoordinatorChanged",
    },
    {
        "_objectType": "groupCoordinatorChanged",
        "groupStatus": "GROUP_STATUS_UPDATED",
        "groupName": "Office + 1",
    },
)
COORDINATOR_MOVED = (
    COORDINATOR_UPDATED[0],
    {
        "_objectType": "groupCoordinatorChanged",
        "groupStatus": "GROUP_STATUS_MOVED",
        "groupName": "Bathroom + 1",
        "websocketUrl": "wss://192.168.113.18:1443/websocket/api",
        "playerId": "RINCON_48A6B86DD3F101400",
    },
)


async def test_group_coordinator_changed_reaches_listeners() -> None:
    """Both recorded groupCoordinatorChanged events reach the listener with their group id."""
    api = _api()
    listener = Mock()
    api.subscribe_group_coordinator_changed(listener)

    api._handle_incoming_message(COORDINATOR_UPDATED)
    api._handle_incoming_message(COORDINATOR_MOVED)
    await _drain()

    assert listener.call_args_list == [
        call(OFFICE_GROUP, COORDINATOR_UPDATED[1]),
        call(OFFICE_GROUP, COORDINATOR_MOVED[1]),
    ]


async def test_group_coordinator_changed_listener_can_stop() -> None:
    """A stopped listener gets no further events; stopping twice is harmless."""
    api = _api()
    listener = Mock()
    unsubscribe = api.subscribe_group_coordinator_changed(listener)

    unsubscribe()
    unsubscribe()
    api._handle_incoming_message(COORDINATOR_MOVED)
    await _drain()

    listener.assert_not_called()


async def test_a_group_coordinator_event_does_not_reach_a_listener_stopped_meanwhile() -> None:
    """An event received just before the handle is used is not delivered after it."""
    api = _api()
    listener = Mock()
    unsubscribe = api.subscribe_group_coordinator_changed(listener)

    api._handle_incoming_message(COORDINATOR_MOVED)
    unsubscribe()
    await _drain()

    listener.assert_not_called()


async def test_a_group_coordinator_listener_registered_twice_stops_one_at_a_time() -> None:
    """A handle stops its own registration only, also when used twice."""
    api = _api()
    listener = Mock()
    unsubscribe_first = api.subscribe_group_coordinator_changed(listener)
    unsubscribe_second = api.subscribe_group_coordinator_changed(listener)

    unsubscribe_first()
    unsubscribe_first()
    api._handle_incoming_message(COORDINATOR_MOVED)
    await _drain()
    listener.assert_called_once_with(OFFICE_GROUP, COORDINATOR_MOVED[1])

    unsubscribe_second()
    api._handle_incoming_message(COORDINATOR_MOVED)
    await _drain()
    listener.assert_called_once_with(OFFICE_GROUP, COORDINATOR_MOVED[1])


async def test_group_coordinator_changed_without_group_is_ignored() -> None:
    """An event without a groupId in its header is not forwarded."""
    api = _api()
    listener = Mock()
    api.subscribe_group_coordinator_changed(listener)

    header = {key: value for key, value in COORDINATOR_MOVED[0].items() if key != "groupId"}
    api._handle_incoming_message((header, COORDINATOR_MOVED[1]))
    await _drain()

    listener.assert_not_called()


async def test_session_error_routed_to_session_error_callback() -> None:
    """An unsolicited sessionError reaches the error callback of its session."""
    api = _api()
    _answer_commands(api)
    error_callback = Mock()
    unsubscribe = await api.playback_session.subscribe("session1", Mock(), error_callback)

    api._handle_incoming_message(
        ({"type": "sessionError", "sessionId": "session1"}, SESSION_EVICTED)
    )
    await _drain()

    error_callback.assert_called_once_with(SESSION_EVICTED)
    unsubscribe()
    assert "session1" not in api.playback_session._subscriptions


async def test_session_error_before_the_subscribe_reply_reaches_the_callback() -> None:
    """An eviction processed while the subscribe command is unanswered is not dropped."""
    api = _api()
    replies, _ = _hold_replies(api)
    error_callback = Mock()

    pending = asyncio.ensure_future(
        api.playback_session.subscribe("session1", Mock(), error_callback)
    )
    await asyncio.sleep(0)
    api._handle_incoming_message(
        ({"type": "sessionError", "sessionId": "session1"}, SESSION_EVICTED)
    )
    await _drain()
    error_callback.assert_called_once_with(SESSION_EVICTED)
    replies[0].set_result(None)
    await pending


async def test_a_refused_session_subscription_leaves_the_earlier_error_listener() -> None:
    """A subscribe the player refuses leaves the listener that was there before it listening."""
    api = _api()
    _answer_commands(api)
    previous = Mock()
    await api.playback_session.subscribe("session1", Mock(), previous)
    api.send_command = AsyncMock(  # type: ignore[method-assign]
        side_effect=FailedCommand("ERROR_COMMAND_FAILED")
    )

    refused = Mock()
    with pytest.raises(FailedCommand):
        await api.playback_session.subscribe("session1", Mock(), refused)

    api._handle_incoming_message(
        ({"type": "sessionError", "sessionId": "session1"}, SESSION_EVICTED)
    )
    await _drain()
    previous.assert_called_once_with(SESSION_EVICTED)
    refused.assert_not_called()


async def test_session_info_and_audio_clip_status_reach_their_listeners() -> None:
    """The sessionInfo and audioClipStatus events are routed by their event type."""
    api = _api()
    _answer_commands(api)
    session_listener = Mock()
    clip_listener = Mock()
    await api.playback_session.subscribe("session1", session_listener)
    await api.audio_clip.subscribe("RINCON_F0F6C1CC8D0401400", clip_listener)
    clips = {"_objectType": "audioClipStatus", "audioClips": []}

    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    api._handle_incoming_message(
        ({"type": "audioClipStatus", "playerId": "RINCON_F0F6C1CC8D0401400"}, clips),
    )
    await _drain()

    session_listener.assert_called_once_with(SESSION_SUSPENDED)
    clip_listener.assert_called_once_with(clips)


async def test_a_refused_first_session_subscription_leaves_no_error_listener() -> None:
    """A subscribe the player refuses, with nothing before it, registers no listener."""
    api = _api()
    api.send_command = AsyncMock(  # type: ignore[method-assign]
        side_effect=FailedCommand("ERROR_COMMAND_FAILED")
    )

    with pytest.raises(FailedCommand):
        await api.playback_session.subscribe("session1", Mock(), Mock())

    assert "session1" not in api.playback_session._subscriptions


async def test_a_session_subscription_failing_late_keeps_a_newer_listener() -> None:
    """A subscribe that fails after a newer one registered neither restores nor removes it."""
    api = _api()
    replies, _ = _hold_replies(api)
    first = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock(), Mock()))
    await asyncio.sleep(0)
    newer = Mock()
    second = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock(), newer))
    await asyncio.sleep(0)
    replies[1].set_result(None)
    unsubscribe_newer = await second
    replies[0].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await first

    api._handle_incoming_message(
        ({"type": "sessionError", "sessionId": "session1"}, SESSION_EVICTED)
    )
    await _drain()
    newer.assert_called_once_with(SESSION_EVICTED)
    unsubscribe_newer()
    assert "session1" not in api.playback_session._subscriptions


async def test_replies_in_reverse_order_leave_the_remaining_subscription_listening() -> None:
    """Two subscribes to a session answered in reverse order: each handle drops its own listener."""
    api = _api()
    replies, commands = _hold_replies(api)
    older_callback, older_error = Mock(), Mock()
    older = asyncio.ensure_future(
        api.playback_session.subscribe("session1", older_callback, older_error)
    )
    await asyncio.sleep(0)
    newer_callback, newer_error = Mock(), Mock()
    newer = asyncio.ensure_future(
        api.playback_session.subscribe("session1", newer_callback, newer_error)
    )
    await asyncio.sleep(0)

    replies[1].set_result(None)
    unsubscribe_newer = await newer
    replies[0].set_result(None)
    unsubscribe_older = await older
    unsubscribe_older()

    commands.assert_not_called()
    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    api._handle_incoming_message(
        ({"type": "sessionError", "sessionId": "session1"}, SESSION_EVICTED)
    )
    await _drain()
    newer_callback.assert_called_once_with(SESSION_SUSPENDED)
    newer_error.assert_called_once_with(SESSION_EVICTED)
    older_callback.assert_not_called()
    older_error.assert_not_called()

    unsubscribe_newer()

    commands.assert_called_once_with(
        namespace="playbackSession", command="unsubscribe", sessionId="session1"
    )
    assert "session1" not in api.playback_session._subscriptions


@pytest.mark.parametrize("cancelled", [False, True])
async def test_a_failing_subscribe_whose_earlier_listener_left_releases(cancelled: bool) -> None:
    """A failing subscribe, the earlier listener gone, releases the speaker's subscription."""
    api = _api()
    _answer_commands(api)
    older_callback = Mock()
    unsubscribe_older = await api.playback_session.subscribe("session1", older_callback, Mock())
    replies, commands = _hold_replies(api)
    newer = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock(), Mock()))
    await asyncio.sleep(0)

    unsubscribe_older()
    # the speaker's subscription serves the newer call for now
    commands.assert_not_called()
    if cancelled:
        newer.cancel()
    else:
        replies[0].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(asyncio.CancelledError if cancelled else FailedCommand):
        await newer

    assert "session1" not in api.playback_session._subscriptions
    # nobody listens: the subscription the older call made is released after all
    commands.assert_called_once_with(
        namespace="playbackSession", command="unsubscribe", sessionId="session1"
    )
    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    await _drain()
    older_callback.assert_not_called()


@pytest.mark.parametrize("held", [False, True])
@pytest.mark.parametrize("cancelled", [False, True], ids=["unanswered", "cancelled"])
async def test_an_unanswered_subscribe_releases_what_the_speaker_may_hold(
    held: bool, cancelled: bool
) -> None:
    """A subscribe without reply, or cancelled, unsubscribes in case it went through."""
    api = _api()
    _answer_commands(api)
    if held:
        await api.playback_session.subscribe("session1", Mock())
    replies, commands = _hold_replies(api)
    pending = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)

    if cancelled:
        pending.cancel()
    else:
        replies[0].set_exception(CommandTimeout("playbackSession:subscribe", 10))
    with pytest.raises(asyncio.CancelledError if cancelled else CommandTimeout):
        await pending

    assert ("session1" in api.playback_session._subscriptions) is held
    if held:
        # the listener still there keeps the speaker's subscription
        commands.assert_not_called()
    else:
        commands.assert_called_once_with(
            namespace="playbackSession", command="unsubscribe", sessionId="session1"
        )


async def test_a_cut_off_subscribe_is_released_by_the_pending_one_that_fails() -> None:
    """A newer call that fails releases what a cancelled older call may have got."""
    api = _api()
    replies, commands = _hold_replies(api)
    older = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)
    newer = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)

    older.cancel()
    with pytest.raises(asyncio.CancelledError):
        await older
    commands.assert_not_called()
    replies[1].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await newer

    assert "session1" not in api.playback_session._subscriptions
    commands.assert_called_once_with(
        namespace="playbackSession", command="unsubscribe", sessionId="session1"
    )


async def test_every_listener_to_a_session_gets_its_events() -> None:
    """Two subscriptions to one session: each listener gets each sessionInfo and sessionError."""
    api = _api()
    commands = _answer_commands(api)
    callbacks = [Mock(), Mock()]
    error_callbacks = [Mock(), Mock()]
    handles = [
        await api.playback_session.subscribe("session1", callback, error_callback)
        for callback, error_callback in zip(callbacks, error_callbacks, strict=True)
    ]

    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    api._handle_incoming_message(
        ({"type": "sessionError", "sessionId": "session1"}, SESSION_EVICTED)
    )
    await _drain()

    for callback, error_callback in zip(callbacks, error_callbacks, strict=True):
        callback.assert_called_once_with(SESSION_SUSPENDED)
        error_callback.assert_called_once_with(SESSION_EVICTED)
    for handle in handles:
        handle()
    commands.assert_called_once()


async def test_a_listener_stopped_by_an_earlier_one_misses_the_event() -> None:
    """A callback that uses another listener's handle stops that listener before its turn."""
    api = _api()
    _answer_commands(api)
    second = Mock()
    await api.playback_session.subscribe("session1", Mock(), lambda _: stop_second())
    stop_second = await api.playback_session.subscribe("session1", Mock(), second)

    api._handle_incoming_message(
        ({"type": "sessionError", "sessionId": "session1"}, SESSION_EVICTED)
    )
    await _drain()

    second.assert_not_called()


async def test_a_listener_stopping_itself_leaves_the_next_one_its_event() -> None:
    """A callback that uses its own handle does not make the listener after it miss the event."""
    api = _api()
    _answer_commands(api)
    second = Mock()
    stop_first = await api.playback_session.subscribe("session1", lambda _: stop_first())
    await api.playback_session.subscribe("session1", second)

    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    await _drain()

    second.assert_called_once_with(SESSION_SUSPENDED)


async def test_a_command_on_a_connection_closed_meanwhile_leaves_no_future() -> None:
    """A command sent after a no-wait one finds the connection gone: InvalidState, no future."""
    api = _api()
    api._ws_client = MagicMock(closed=False)

    async def _send_bytes(_raw: bytes) -> None:
        api._ws_client.closed = True

    api._ws_client.send_bytes = _send_bytes
    api.send_command_no_wait("playbackSession", "unsubscribe", sessionId="session1")
    with pytest.raises(InvalidState):
        await api.send_command("playbackSession", "subscribe", sessionId="session2")

    assert api._result_futures == {}


async def test_a_command_whose_frame_cannot_be_written_leaves_no_future() -> None:
    """A command the socket will not take is not left waiting for a reply."""
    api = _api()
    api._ws_client = MagicMock(closed=False)
    api._ws_client.send_bytes = AsyncMock(side_effect=ConnectionResetError)

    with pytest.raises(ConnectionResetError):
        await api.send_command("playbackSession", "subscribe", sessionId="session1")

    assert api._result_futures == {}


@pytest.mark.parametrize("cancelled", [False, True], ids=["unanswered", "cancelled"])
async def test_a_cut_off_subscribe_is_released_when_the_earlier_call_is_refused(
    cancelled: bool,
) -> None:
    """What a cut-off call may hold is released by the last listener to leave."""
    api = _api()
    replies, commands = _hold_replies(api)
    older = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)
    newer = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)

    if cancelled:
        newer.cancel()
    else:
        replies[1].set_exception(CommandTimeout("playbackSession:subscribe", 10))
    with pytest.raises(asyncio.CancelledError if cancelled else CommandTimeout):
        await newer
    # the older call still listens, so what the newer one may have got stays for it
    commands.assert_not_called()
    replies[0].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await older

    assert "session1" not in api.playback_session._subscriptions
    commands.assert_called_once_with(
        namespace="playbackSession", command="unsubscribe", sessionId="session1"
    )


async def test_a_command_goes_out_after_the_commands_sent_without_waiting_before_it() -> None:
    """A command awaited for its reply does not overtake one sent without waiting just before."""
    api = _api()
    frames: list[str] = []
    api._ws_client = MagicMock(closed=False)

    async def _send_bytes(raw: bytes) -> None:
        header = orjson.loads(raw)[0]
        frames.append(f"{header['command']} {header['sessionId']}")
        if header["command"] == "subscribe":
            api._result_futures[header["cmdId"]].set_result({})

    api._ws_client.send_bytes = _send_bytes
    api.send_command_no_wait("playbackSession", "unsubscribe", sessionId="session1")
    await api.send_command("playbackSession", "subscribe", sessionId="session2")

    assert frames == ["unsubscribe session1", "subscribe session2"]


async def test_releasing_a_given_up_subscription_on_a_dead_connection_keeps_the_failure() -> None:
    """The unsubscribe sent for a given-up subscription does not mask why the subscribe failed."""
    api = _api()
    _answer_commands(api)
    unsubscribe_older = await api.playback_session.subscribe("session1", Mock())
    replies, commands = _hold_replies(api)
    newer = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)

    unsubscribe_older()
    commands.side_effect = InvalidState("Not connected")
    replies[0].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await newer

    commands.assert_called_once()
    assert "session1" not in api.playback_session._subscriptions


@pytest.mark.parametrize("held", [False, True])
async def test_a_cancelled_subscribe_leaves_the_session_as_it_was(held: bool) -> None:
    """A subscribe cancelled while unanswered leaves no listener, or only the earlier one."""
    api = _api()
    _answer_commands(api)
    holder = Mock()
    if held:
        await api.playback_session.subscribe("session1", holder)
    _, commands = _hold_replies(api)
    cancelled_callback = Mock()
    pending = asyncio.ensure_future(api.playback_session.subscribe("session1", cancelled_callback))
    await asyncio.sleep(0)

    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert ("session1" in api.playback_session._subscriptions) is held
    # the speaker may have taken the subscribe: released unless the holder keeps it
    assert commands.call_count == (0 if held else 1)
    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    await _drain()
    cancelled_callback.assert_not_called()
    assert holder.call_count == (1 if held else 0)


async def test_two_refused_subscribes_in_flight_leave_no_subscription() -> None:
    """Two subscribes the player refuses leave no listener and nothing to release."""
    api = _api()
    replies, commands = _hold_replies(api)
    older_callback, newer_callback = Mock(), Mock()
    older = asyncio.ensure_future(api.playback_session.subscribe("session1", older_callback))
    await asyncio.sleep(0)
    newer = asyncio.ensure_future(api.playback_session.subscribe("session1", newer_callback))
    await asyncio.sleep(0)

    replies[0].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await older
    replies[1].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await newer

    assert "session1" not in api.playback_session._subscriptions
    # the speaker accepted neither: nothing to release
    commands.assert_not_called()
    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    await _drain()
    older_callback.assert_not_called()
    newer_callback.assert_not_called()


async def test_refused_subscribes_leave_the_earlier_listener_alone() -> None:
    """Two later subscribes that both fail change nothing for the listener already there."""
    api = _api()
    _answer_commands(api)
    holder = Mock()
    unsubscribe_holder = await api.playback_session.subscribe("session1", holder)
    replies, commands = _hold_replies(api)
    second = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)
    third = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)

    replies[0].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await second
    replies[1].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await third

    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    await _drain()
    holder.assert_called_once_with(SESSION_SUSPENDED)
    unsubscribe_holder()
    commands.assert_called_once_with(
        namespace="playbackSession", command="unsubscribe", sessionId="session1"
    )
    assert "session1" not in api.playback_session._subscriptions


async def test_a_listener_whose_handle_is_unused_keeps_listening() -> None:
    """Later subscribes to the same id, used or failed, do not end an earlier listener."""
    api = _api()
    _answer_commands(api)
    first = Mock()
    unsubscribe_first = await api.playback_session.subscribe("session1", first)
    unsubscribe_second = await api.playback_session.subscribe("session1", Mock())
    replies, commands = _hold_replies(api)
    third = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock()))
    await asyncio.sleep(0)

    unsubscribe_second()
    replies[0].set_exception(FailedCommand("ERROR_COMMAND_FAILED"))
    with pytest.raises(FailedCommand):
        await third

    commands.assert_not_called()
    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    await _drain()
    first.assert_called_once_with(SESSION_SUSPENDED)
    unsubscribe_first()
    commands.assert_called_once()
    assert "session1" not in api.playback_session._subscriptions


async def test_unsubscribing_a_session_leaves_a_newer_subscription_alone() -> None:
    """The handle of an older subscription to a session leaves the newer one subscribed."""
    api = _api()
    commands = _answer_commands(api)
    error_callback = Mock()
    unsubscribe_older = await api.playback_session.subscribe("session1", Mock(), error_callback)
    newer = Mock()
    unsubscribe_newer = await api.playback_session.subscribe("session1", newer, error_callback)

    unsubscribe_older()

    commands.assert_not_called()
    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, SESSION_SUSPENDED),
    )
    api._handle_incoming_message(
        ({"type": "sessionError", "sessionId": "session1"}, SESSION_EVICTED)
    )
    await _drain()
    newer.assert_called_once_with(SESSION_SUSPENDED)
    error_callback.assert_called_once_with(SESSION_EVICTED)

    unsubscribe_newer()

    commands.assert_called_once_with(
        namespace="playbackSession", command="unsubscribe", sessionId="session1"
    )
    assert "session1" not in api.playback_session._subscriptions


async def test_unsubscribing_a_group_leaves_a_newer_playback_subscription_alone() -> None:
    """The handle of an older playback subscription leaves the newer one's error listener."""
    api = _api()
    commands = _answer_commands(api)
    error_callback = Mock()
    unsubscribe_older = await api.playback.subscribe(GROUP, Mock(), error_callback)
    unsubscribe_newer = await api.playback.subscribe(GROUP, Mock(), error_callback)

    unsubscribe_older()

    commands.assert_not_called()
    error = {"errorCode": "ERROR_PLAYBACK_FAILED", "reason": "no"}
    api._handle_incoming_message(({"type": "playbackError", "groupId": GROUP}, error))
    await _drain()
    error_callback.assert_called_once_with(error)

    unsubscribe_newer()

    commands.assert_called_once_with(namespace="playback", command="unsubscribe", groupId=GROUP)
    assert GROUP not in api.playback._subscriptions


@pytest.mark.parametrize(
    ("namespace", "event_key"),
    [("playback", "groupId"), ("playback_session", "sessionId")],
)
async def test_an_error_for_a_subscription_without_error_callback_is_dropped(
    namespace: str, event_key: str
) -> None:
    """A subscription made without an error callback takes its namespace's errors silently."""
    api = _api()
    _answer_commands(api)
    await getattr(api, namespace).subscribe("id1", Mock())

    await getattr(api, namespace)._handle_error_event({event_key: "id1"}, {"errorCode": "ERROR"})


async def test_a_used_unsubscribe_handle_sends_nothing_and_leaves_other_listeners() -> None:
    """A handle unsubscribes once and drops its own listener only; used again, it is a no-op."""
    api = _api()
    commands = _answer_commands(api)
    unsubscribe_older = await api.player_volume.subscribe("player1", Mock())
    newer = Mock()
    unsubscribe_newer = await api.player_volume.subscribe("player1", newer)

    unsubscribe_older()
    unsubscribe_older()
    listeners = api.player_volume._subscriptions["player1"].listeners
    assert [listener.callback for listener in listeners] == [newer]
    unsubscribe_newer()
    unsubscribe_newer()

    commands.assert_called_once_with(
        namespace="playerVolume", command="unsubscribe", playerId="player1"
    )
    assert "player1" not in api.player_volume._subscriptions
