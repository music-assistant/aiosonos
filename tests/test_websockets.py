"""Tests for routing incoming websocket messages."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, Mock

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
    api.logger.setLevel(logging.DEBUG)

    with caplog.at_level(logging.DEBUG):
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
