"""Tests for the playbackSession leaveSession command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiosonos.api.namespaces.playback_session import PlaybackSessionNameSpace


def _namespace() -> tuple[PlaybackSessionNameSpace, AsyncMock]:
    api = MagicMock()
    api.send_command = AsyncMock(return_value={})
    return PlaybackSessionNameSpace(api), api.send_command


async def test_leave_session_sends_an_empty_body_by_default() -> None:
    """The command goes to the session with no body fields unless a queue version is given."""
    namespace, send_command = _namespace()

    await namespace.leave_session("session1")

    send_command.assert_awaited_once_with(
        namespace="playbackSession",
        command="leaveSession",
        sessionId="session1",
        options={},
    )


async def test_leave_session_sends_the_queue_version_when_given() -> None:
    """The queue version the controller had at hand is passed as queueVersion."""
    namespace, send_command = _namespace()

    await namespace.leave_session("session1", queue_version="v2")

    assert send_command.await_args.kwargs["options"] == {"queueVersion": "v2"}
