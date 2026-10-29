"""Tests for a command whose reply never arrives."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiosonos.api import websockets
from aiosonos.api.websockets import SonosLocalWebSocketsApi
from aiosonos.exceptions import CommandTimeout, FailedCommand
from aiosonos.group import SonosGroup


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


async def test_stop_timeout_does_not_clear_queue() -> None:
    """An unanswered leave is raised; the queue-clearing fallback is not sent."""
    client = MagicMock()
    client.api.playback_session.leave_session = AsyncMock(
        side_effect=CommandTimeout("playbackSession:leaveSession", 10),
    )
    client.api.playback_session.create_session = AsyncMock()
    group = SonosGroup(client, {"id": "group1"})
    group.active_session_id = "session1"

    with pytest.raises(CommandTimeout):
        await group.stop()

    client.api.playback_session.create_session.assert_not_called()
    assert group.active_session_id is None


async def test_stop_fallback_timeout_is_raised() -> None:
    """A refused leave falls back to clearing the queue; that going unanswered is raised too."""
    client = MagicMock()
    client.api.playback_session.leave_session = AsyncMock(
        side_effect=FailedCommand("ERROR_INVALID_PARAMETER"),
    )
    client.api.playback_session.create_session = AsyncMock(
        side_effect=CommandTimeout("playbackSession:createSession", 10),
    )
    group = SonosGroup(client, {"id": "group1"})
    group.active_session_id = "session1"

    with pytest.raises(CommandTimeout):
        await group.stop()

    client.api.playback_session.leave_session.assert_awaited_once_with("session1")
    assert group.active_session_id is None


async def test_stop_fallback_refusal_is_still_suppressed() -> None:
    """A fallback leave the speaker answers with an error is logged; the stop is done."""
    client = MagicMock()
    client.api.playback_session.leave_session = AsyncMock(
        side_effect=[
            FailedCommand("ERROR_INVALID_PARAMETER"),
            FailedCommand("ERROR_PLAYBACK_FAILED"),
        ],
    )
    client.api.playback_session.create_session = AsyncMock(return_value={"sessionId": "s2"})
    client.api.playback_session.subscribe = AsyncMock(return_value=MagicMock())
    group = SonosGroup(client, {"id": "group1"})
    group.active_session_id = "session1"

    await group.stop()

    assert client.api.playback_session.leave_session.await_args_list[1].args == ("s2",)
    assert group.active_session_id is None


@pytest.mark.parametrize(
    "reply",
    [
        {"success": True, "type": "playbackStatus"},
        {"success": False, "type": "none"},
    ],
    ids=["success", "failure"],
)
async def test_reply_after_timeout_cancel_is_dropped(reply: dict[str, object]) -> None:
    """A reply for a command whose timeout already cancelled its future does not raise."""
    api = _api()
    future = api._loop.create_future()
    future.cancel()
    api._result_futures["cmd1"] = future

    api._handle_incoming_message(({"cmdId": "cmd1", **reply}, {"_objectType": "x"}))
    api._handle_incoming_message(({"cmdId": "cmd1"}, {"errorCode": "ERROR", "reason": "late"}))

    assert future.cancelled()
