"""Tests for the incoming websocket message handler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import WSMsgType

from aiosonos.api.websockets import SonosLocalWebSocketsApi
from aiosonos.exceptions import FailedCommand, InvalidMessage


def _api() -> SonosLocalWebSocketsApi:
    api = SonosLocalWebSocketsApi("wss://1.2.3.4:1443/websocket/api", MagicMock())
    api._loop = asyncio.get_running_loop()
    api._ws_client = MagicMock(closed=False)
    api._send_message = AsyncMock()
    return api


async def test_failed_reply_without_object_type_fails_the_command() -> None:
    """A failed reply with neither errorCode nor _objectType still fails the command cleanly."""
    api = _api()
    future = api._loop.create_future()
    api._result_futures["cmd1"] = future

    api._handle_incoming_message(({"cmdId": "cmd1", "success": False}, {}))

    with pytest.raises(FailedCommand) as excinfo:
        await future
    assert excinfo.value.error_code == "unknown"


async def test_group_coordinator_changed_reply_keeps_its_object_type() -> None:
    """The body of a refused group command names the refusal, as callers expect."""
    api = _api()
    future = api._loop.create_future()
    api._result_futures["cmd1"] = future

    api._handle_incoming_message(
        (
            {"cmdId": "cmd1", "success": False, "type": "groupCoordinatorChanged"},
            {"_objectType": "groupCoordinatorChanged", "groupStatus": "GROUP_STATUS_MOVED"},
        ),
    )

    with pytest.raises(FailedCommand) as excinfo:
        await future
    assert excinfo.value.error_code == "groupCoordinatorChanged"


async def test_invalid_json_raises_invalid_message() -> None:
    """Undecodable text from the player is reported, not crashed on."""
    api = _api()
    api._ws_client.receive = AsyncMock(return_value=MagicMock(type=WSMsgType.TEXT, data="{nope"))

    with pytest.raises(InvalidMessage):
        await api.receive_message_or_raise()


async def test_unsupported_payload_raises_invalid_message() -> None:
    """A payload the decoder refuses outright is reported, not crashed on."""
    api = _api()
    api._ws_client.receive = AsyncMock(return_value=MagicMock(type=WSMsgType.TEXT, data=object()))

    with pytest.raises(InvalidMessage):
        await api.receive_message_or_raise()
