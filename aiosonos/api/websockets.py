"""
Websocket API client for Sonos devices.

Simple wrapper for the Websocket API provided by Sonos which runs in the cloud,
but also locally on every Sonos speaker.

As far as I can oversee, the websockets API only runs locally on the Sonos speakers
and is not available in the cloud. The cloud API is a REST API and is documented here:
https://developer.sonos.com/reference

The objects, namespaces and commands however are all the same between the two APIs.
So at one point an alternative version of this client could be created
to support the cloud API as well.

In that case, commands are sent by regular HTTP GET/POST/PUT/DELETE requests,
and events received by a callback URL that you have to provide to the Sonos cloud API.
"""
from __future__ import annotations

import asyncio
import logging
import pprint
import ssl
import uuid
from typing import TYPE_CHECKING, Any, Self

import orjson
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType, client_exceptions

from aiosonos.api.models import CommandMessage, ResultMessage
from aiosonos.api.namespaces.audioclip import AudioClipNameSpace
from aiosonos.api.namespaces.groups import GroupsNameSpace
from aiosonos.api.namespaces.player_volume import PlayerVolumeNameSpace
from aiosonos.const import LOCAL_API_TOKEN, LOG_LEVEL_VERBOSE
from aiosonos.exceptions import (
    CannotConnect,
    ConnectionClosed,
    ConnectionFailed,
    FailedCommand,
    InvalidMessage,
    InvalidState,
    NotConnected,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from types import TracebackType

    from aiohttp import ClientSession

VERBOSE_LOGGER = True


class SonosLocalWebSocketsApi:
    """Manage a Sonos Speaker using the local websockets api."""

    def __init__(
        self,
        websocket_url: str,
        aiohttp_session: ClientSession,
    ) -> None:
        """Initialize the Sonos API Connection to a local player's websocket."""
        self._aiohttp_session = aiohttp_session
        self.websocket_url = websocket_url
        self.logger = logging.getLogger(__package__)
        self._stop_called: bool = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audioclip = AudioClipNameSpace(self)
        self._groups = GroupsNameSpace(self)
        self._player_volume = PlayerVolumeNameSpace(self)
        self._tracked_tasks: dict[str, asyncio.Task] = {}
        self._ws_client: ClientWebSocketResponse | None = None
        self._result_futures: dict[str, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        """Return if we're currently connected."""
        return self._ws_client is not None and not self._ws_client.closed

    @property
    def audioclip(self) -> AudioClipNameSpace:
        """Return AudioClip namespace handler."""
        return self._audioclip

    @property
    def groups(self) -> GroupsNameSpace:
        """Return Groups namespace handler."""
        return self._groups

    @property
    def player_volume(self) -> PlayerVolumeNameSpace:
        """Return PlayerVolume namespace handler."""
        return self._player_volume

    async def send_command(
        self,
        namespace: str,
        command: str,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Send a command and get a response."""
        if not self.connected or not self._loop:
            raise InvalidState("Not connected")

        command_message = CommandMessage(
            namespace=namespace,
            command=command,
            cmdId=uuid.uuid4().hex,
            # path params are passed as kwargs
            **kwargs,
        )
        future: asyncio.Future[Any] = self._loop.create_future()
        self._result_futures[command_message["cmdId"]] = future
        # body params are passed as options
        await self._send_message([command_message, options or {}])
        try:
            return await future
        finally:
            self._result_futures.pop(command_message["cmdId"])

    def send_command_no_wait(
        self,
        namespace: str,
        command: str,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a command without waiting for the response."""
        if not self.connected:
            msg = "Not connected"
            raise InvalidState(msg)

        command_message = CommandMessage(
            namespace=namespace,
            command=command,
            cmdId=uuid.uuid4().hex,
            # path params are passed as kwargs
            **kwargs,
        )
        # body params are passed as options
        self.create_task(self._send_message([command_message, options or {}]))

    async def start_listening(self, init_ready: asyncio.Event | None = None) -> None:
        """Connect (if needed) and start listening to incoming messages from the server."""
        if not self.connected:
            await self.connect()

        if init_ready is not None:
            init_ready.set()

        try:
            # keep reading incoming messages
            while not self._stop_called:
                msg = await self.receive_message_or_raise()
                self._handle_incoming_message(msg)
        except ConnectionClosed:
            pass
        finally:
            await self.disconnect()

    async def connect(self) -> None:
        """Connect to the websocket server."""
        self._loop = asyncio.get_running_loop()
        if self._ws_client is not None:
            raise InvalidState("Already connected")

        self.logger.debug("Trying to connect to %s", self.websocket_url)

        headers = {
            "X-Sonos-Api-Key": LOCAL_API_TOKEN,
            "Sec-Websocket-Protocol": "v1.api.smartspeaker.audio",
        }
        try:
            self._ws_client = await self._aiohttp_session.ws_connect(
                self.websocket_url,
                heartbeat=55,
                compress=15,
                max_msg_size=0,
                headers=headers,
                ssl=ssl.SSLContext(ssl.PROTOCOL_TLSv1_2),
            )
        except (
            client_exceptions.WSServerHandshakeError,
            client_exceptions.ClientError,
        ) as err:
            raise CannotConnect(err) from err

        self.logger.info(
            "Connected to Sonos Websocket (%s)",
            self.websocket_url,
        )

    async def disconnect(self) -> None:
        """Disconnect the client and cleanup."""
        self._stop_called = True
        # cancel all command-tasks awaiting a result
        for future in self._result_futures.values():
            future.cancel()
        self.logger.debug("Closing client connection")
        if self._ws_client is not None and not self._ws_client.closed:
            await self._ws_client.close()
        self._ws_client = None

    def create_task(
        self,
        target: Awaitable,
    ) -> asyncio.Task:
        """
        Create Task on (main) event loop from Coroutine(function).

        Tasks created by this helper will be properly cancelled on stop,
        and exceptions will be logged.
        """

        def task_done_callback(_task: asyncio.Future | asyncio.Task) -> None:
            _task_id = task.task_id
            self._tracked_tasks.pop(_task_id)
            # log unhandled exceptions
            if not _task.cancelled() and (err := _task.exception()):
                task_name = _task.get_name() if hasattr(_task, "get_name") else str(_task)
                self.logger.warning(
                    "Exception in task %s - target: %s: %s",
                    task_name,
                    str(target),
                    str(err),
                    exc_info=err if self.logger.isEnabledFor(logging.DEBUG) else None,
                )

        task = self._loop.create_task(target)
        task_id = uuid.uuid4().hex
        task.task_id = task_id
        self._tracked_tasks[task_id] = task
        task.add_done_callback(task_done_callback)
        return task

    async def __aenter__(self) -> Self:
        """Initialize and connect the connection to the SonosApi."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """Exit context manager."""
        await self.disconnect()

    def __repr__(self) -> str:
        """Return the representation."""
        conn_type = self.__class__.__name__
        prefix = "" if self.connected else "not "
        return f"{type(self).__name__}(connection={conn_type}, {prefix}connected)"

    def _handle_incoming_message(self, raw: tuple[ResultMessage, dict[str, Any]]) -> None:
        """
        Handle incoming message.

        Run all async tasks in a wrapper to log appropriately.
        """
        msg, msg_data = raw
        # handle command result message
        if "success" in raw[0]:
            future = self._result_futures.get(msg["cmdId"])
            if future is None:
                # no listener for this result
                return
            if msg["success"]:
                future.set_result(msg_data)
            else:
                future.set_exception(FailedCommand(msg_data["errorCode"], msg_data["reason"]))
            return

        # handle EventMessage
        if event_type := msg.get("type"):
            # handle namespace specific events
            for namespace in (self._audioclip, self._groups, self._player_volume):
                if event_type == namespace.event_type:
                    self.create_task(namespace._handle_event(msg, msg_data))  # noqa: SLF001
                    break
            else:
                self.logger.debug(
                    "Received unhandled event type: %s: %s",
                    event_type,
                    msg,
                )
            return

        # Log anything we can't handle here
        self.logger.debug("Received unhandled message: %s", msg)

    async def receive_message_or_raise(self) -> tuple[ResultMessage, dict[str, Any]]:
        """Receive (raw) message or raise."""
        assert self._ws_client
        ws_msg = await self._ws_client.receive()

        if ws_msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING):
            raise ConnectionClosed("Connection was closed.")

        if ws_msg.type == WSMsgType.ERROR:
            raise ConnectionFailed

        if ws_msg.type != WSMsgType.TEXT:
            err_msg = f"Received non-Text message: {ws_msg.type}: {ws_msg.data}"
            raise InvalidMessage(err_msg)

        try:
            msg = orjson.loads(ws_msg.data)
        except TypeError as err:
            err_msg = f"Received unsupported JSON: {err}"
            raise InvalidMessage(msg) from err_msg
        except ValueError as err:
            raise InvalidMessage("Received invalid JSON.") from err

        if self.logger.isEnabledFor(LOG_LEVEL_VERBOSE):
            self.logger.log(LOG_LEVEL_VERBOSE, "Received message:\n%s\n", pprint.pformat(ws_msg))

        return msg

    async def _send_message(self, message: tuple[CommandMessage, dict[str, Any]]) -> None:
        """
        Send a message to the server.

        Raises NotConnected if client not connected.
        """
        if not self.connected:
            raise NotConnected

        if self.logger.isEnabledFor(LOG_LEVEL_VERBOSE):
            self.logger.log(LOG_LEVEL_VERBOSE, "Publishing message:\n%s\n", pprint.pformat(message))

        assert self._ws_client
        # sonos messages are always an array of 2 dict objects
        assert isinstance(message, list)

        await self._ws_client.send_bytes(orjson.dumps(message))
