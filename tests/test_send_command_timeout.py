"""Tests for a command whose reply never arrives."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiosonos.api import websockets
from aiosonos.api.websockets import SonosLocalWebSocketsApi
from aiosonos.exceptions import CommandTimeout, FailedCommand


def _api() -> SonosLocalWebSocketsApi:
    api = SonosLocalWebSocketsApi("wss://1.2.3.4:1443/websocket/api", MagicMock())
    api._loop = asyncio.get_running_loop()
    api._ws_client = MagicMock(closed=False)
    api._send_message = AsyncMock()
    return api


async def test_no_reply_raises_command_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command the player never answers fails after the timeout, as a FailedCommand."""
    monkeypatch.setattr(websockets, "COMMAND_TIMEOUT", 0.05)
    api = _api()

    with pytest.raises(CommandTimeout) as excinfo:
        await api.send_command("playback", "pause", groupId="group1")

    assert isinstance(excinfo.value, FailedCommand)
    assert excinfo.value.error_code == "ERROR_TIMEOUT"
    assert "playback:pause" in str(excinfo.value)
    # the pending reply slot is released, so a late reply is dropped rather than leaked
    assert api._result_futures == {}


async def test_reply_in_time_resolves() -> None:
    """A reply that arrives before the timeout is returned as before."""
    api = _api()

    async def _reply() -> None:
        await asyncio.sleep(0)
        (cmd_id,) = api._result_futures
        api._handle_incoming_message(
            ({"cmdId": cmd_id, "success": True, "type": "playbackStatus"}, {"playbackState": "x"}),
        )

    api._loop.create_task(_reply())
    result = await api.send_command("playback", "getPlaybackStatus", groupId="group1")

    assert result == {"playbackState": "x"}
    assert api._result_futures == {}
