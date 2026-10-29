"""Tests for a stop whose leave reply and session events arrive in one read, on either factory."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

from aiosonos.api.websockets import SonosLocalWebSocketsApi
from aiosonos.client import SonosLocalApiClient
from aiosonos.group import SonosGroup

PLAYER = "RINCON_F0F6C1CC8D0401400"
EVICTED = "ERROR_SESSION_EVICTED"

FACTORIES = [
    pytest.param(False, id="lazy"),
    pytest.param(
        True,
        id="eager",
        marks=pytest.mark.skipif(sys.version_info < (3, 12), reason="no eager task factory"),
    ),
]


def _group(
    foreign_eviction: bool, leave_error: str | None
) -> tuple[SonosLocalApiClient, SonosGroup]:
    """Build a real api and group over a fake speaker that answers each command next tick."""
    loop = asyncio.get_running_loop()
    api = SonosLocalWebSocketsApi("wss://1.2.3.4:1443/websocket/api", MagicMock())
    api._loop = loop
    api._ws_client = MagicMock(closed=False)

    def _event(reason: str) -> None:
        api._handle_incoming_message(
            (
                {"type": "sessionError", "sessionId": "session1"},
                {"errorCode": EVICTED, "reason": reason},
            )
        )

    async def _send(message: list) -> None:
        command, _ = message
        cmd_id, name = command.get("cmdId"), command["command"]

        def _reply() -> None:
            if name == "createSession":
                api._handle_incoming_message(
                    ({"cmdId": cmd_id, "success": True}, {"sessionId": "session1"})
                )
            elif name == "subscribe":
                api._handle_incoming_message(({"cmdId": cmd_id, "success": True}, {}))
            elif name == "leaveSession":
                if foreign_eviction:
                    _event("Another user joined the session.")
                if leave_error:
                    api._handle_incoming_message(({"cmdId": cmd_id}, {"errorCode": leave_error}))
                    return
                api._handle_incoming_message(({"cmdId": cmd_id, "success": True}, {}))
                # the same read: the speaker reports the eviction the leave itself raised
                _event("Leaving Muse session")

        if name != "unsubscribe":
            loop.call_soon(_reply)

    api._send_message = _send
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._player_id = PLAYER
    client._loop = loop
    client.signal_event = MagicMock()
    client.api = api
    group = SonosGroup(client, {"id": "group1", "coordinatorId": PLAYER, "playerIds": [PLAYER]})
    return client, group


async def _stop_on(eager: bool, foreign_eviction: bool, leave_error: str | None) -> tuple:
    """Create a session and stop, on the lazy or the eager task factory."""
    loop = asyncio.get_running_loop()
    if eager:
        loop.set_task_factory(asyncio.eager_task_factory)
    try:
        client, group = _group(foreign_eviction, leave_error)
        await group.create_playback_session()
        await group.stop()
        for _ in range(5):
            await asyncio.sleep(0)
    finally:
        loop.set_task_factory(None)
    return client, group


@pytest.mark.parametrize("eager", FACTORIES)
async def test_a_stops_own_eviction_read_with_the_reply_is_not_signalled(eager: bool) -> None:
    """The eviction a leave raises, read together with its reply, is not taken for a takeover."""
    client, group = await _stop_on(eager, foreign_eviction=False, leave_error=None)

    client.signal_event.assert_not_called()
    assert group._evictions == 0
    assert group.active_session_id is None


@pytest.mark.parametrize("eager", FACTORIES)
async def test_a_takeover_read_before_the_leave_reply_is_signalled_once(eager: bool) -> None:
    """A foreign eviction read just before the leave's refusal is signalled once, with no clear."""
    client, group = await _stop_on(
        eager, foreign_eviction=True, leave_error="ERROR_INVALID_OBJECT_ID"
    )

    client.signal_event.assert_called_once()
    assert client.signal_event.call_args.args[0].data["sessionId"] == "session1"
    assert group._evictions == 1
    assert group.active_session_id is None
