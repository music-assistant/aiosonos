"""Tests for routing incoming websocket messages."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, Mock, call

import pytest

from aiosonos.api import SonosLocalWebSocketsApi
from aiosonos.exceptions import FailedCommand

if TYPE_CHECKING:
    from aiosonos.api.namespaces._base import UnsubscribeCallbackType

GROUP = "group1"


def _api() -> SonosLocalWebSocketsApi:
    api = SonosLocalWebSocketsApi("wss://1.2.3.4:1443/websocket/api", MagicMock())
    api._loop = asyncio.get_running_loop()
    return api


async def _subscribe_playback(
    api: SonosLocalWebSocketsApi, **kwargs: Mock
) -> UnsubscribeCallbackType:
    api._playback._handle_subscribe = AsyncMock(return_value=Mock())  # type: ignore[method-assign]
    return await api.playback.subscribe(GROUP, Mock(), **kwargs)


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


async def test_playback_subscribe_keeps_error_listener_in_sync() -> None:
    """Subscribing again and unsubscribing replace and drop the error listener."""
    api = _api()
    error_callback = Mock()
    await _subscribe_playback(api, error_callback=error_callback)
    assert api.playback._error_listeners[GROUP] is error_callback

    await _subscribe_playback(api)
    assert GROUP not in api.playback._error_listeners

    unsubscribe = await _subscribe_playback(api, error_callback=error_callback)
    unsubscribe()
    assert GROUP not in api.playback._error_listeners


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
    api._playback_session._handle_subscribe = AsyncMock(return_value=Mock())  # type: ignore[method-assign]
    error_callback = Mock()
    unsubscribe = await api.playback_session.subscribe("session1", Mock(), error_callback)
    error = {"errorCode": "ERROR_SESSION_EVICTED", "reason": "Another user joined the session."}

    api._handle_incoming_message(({"type": "sessionError", "sessionId": "session1"}, error))
    await _drain()

    error_callback.assert_called_once_with(error)
    unsubscribe()
    assert "session1" not in api.playback_session._error_listeners


async def test_session_error_before_the_subscribe_reply_reaches_the_callback() -> None:
    """An eviction processed while the subscribe command is unanswered is not dropped."""
    api = _api()
    replied = asyncio.Event()

    async def _handle_subscribe(*_: object) -> Mock:
        await replied.wait()
        return Mock()

    api._playback_session._handle_subscribe = _handle_subscribe  # type: ignore[method-assign]
    error_callback = Mock()
    error = {"errorCode": "ERROR_SESSION_EVICTED", "reason": "Another user joined the session."}

    pending = asyncio.ensure_future(
        api.playback_session.subscribe("session1", Mock(), error_callback)
    )
    await asyncio.sleep(0)
    api._handle_incoming_message(({"type": "sessionError", "sessionId": "session1"}, error))
    await _drain()
    error_callback.assert_called_once_with(error)
    replied.set()
    await pending


async def test_a_refused_session_subscription_restores_the_previous_error_listener() -> None:
    """A subscribe the player refuses leaves the listener that was there before it."""
    api = _api()
    api._playback_session._handle_subscribe = AsyncMock(return_value=Mock())  # type: ignore[method-assign]
    previous = Mock()
    await api.playback_session.subscribe("session1", Mock(), previous)
    api._playback_session._handle_subscribe = AsyncMock(  # type: ignore[method-assign]
        side_effect=FailedCommand("ERROR_COMMAND_FAILED")
    )

    with pytest.raises(FailedCommand):
        await api.playback_session.subscribe("session1", Mock(), Mock())

    assert api.playback_session._error_listeners["session1"] is previous


async def test_session_info_and_audio_clip_status_reach_their_listeners() -> None:
    """The sessionInfo and audioClipStatus events are routed by their event type."""
    api = _api()
    session_listener = Mock()
    clip_listener = Mock()
    api.playback_session._listeners["session1"] = session_listener
    api.audio_clip._listeners["RINCON_F0F6C1CC8D0401400"] = clip_listener
    clips = {"_objectType": "audioClipStatus", "audioClips": []}

    api._handle_incoming_message(
        ({"type": "sessionInfo", "sessionId": "session1"}, {"suspended": True}),
    )
    api._handle_incoming_message(
        ({"type": "audioClipStatus", "playerId": "RINCON_F0F6C1CC8D0401400"}, clips),
    )
    await _drain()

    session_listener.assert_called_once_with({"suspended": True})
    clip_listener.assert_called_once_with(clips)


async def test_a_refused_first_session_subscription_leaves_no_error_listener() -> None:
    """A subscribe the player refuses, with nothing before it, registers no listener."""
    api = _api()
    api._playback_session._handle_subscribe = AsyncMock(  # type: ignore[method-assign]
        side_effect=FailedCommand("ERROR_COMMAND_FAILED")
    )

    with pytest.raises(FailedCommand):
        await api.playback_session.subscribe("session1", Mock(), Mock())

    assert "session1" not in api.playback_session._error_listeners


async def test_a_session_subscription_failing_late_keeps_a_newer_listener() -> None:
    """A subscribe that fails after a newer one registered neither restores nor removes it."""
    api = _api()
    first_reply = asyncio.Event()

    async def _first(*_: object) -> Mock:
        await first_reply.wait()
        raise FailedCommand("ERROR_COMMAND_FAILED")

    api._playback_session._handle_subscribe = _first  # type: ignore[method-assign]
    first = asyncio.ensure_future(api.playback_session.subscribe("session1", Mock(), Mock()))
    await asyncio.sleep(0)
    api._playback_session._handle_subscribe = AsyncMock(return_value=Mock())  # type: ignore[method-assign]
    newer = Mock()
    unsubscribe_newer = await api.playback_session.subscribe("session1", Mock(), newer)
    first_reply.set()
    with pytest.raises(FailedCommand):
        await first

    assert api.playback_session._error_listeners["session1"] is newer
    unsubscribe_newer()
    assert "session1" not in api.playback_session._error_listeners


async def test_unsubscribing_a_session_leaves_a_newer_listener_alone() -> None:
    """The unsubscribe handle of an older subscription does not drop a newer one's listener."""
    api = _api()
    api._playback_session._handle_subscribe = AsyncMock(return_value=Mock())  # type: ignore[method-assign]
    unsubscribe_older = await api.playback_session.subscribe("session1", Mock(), Mock())
    newer = Mock()
    await api.playback_session.subscribe("session1", Mock(), newer)

    unsubscribe_older()

    assert api.playback_session._error_listeners["session1"] is newer
