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
import pprint
import uuid
from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast

import orjson
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType, client_exceptions

from aiosonos.api.models import CommandMessage, ResultMessage
from aiosonos.const import LOCAL_API_TOKEN, LOG_LEVEL_VERBOSE
from aiosonos.exceptions import (
    CannotConnect,
    CommandTimeout,
    ConnectionClosed,
    ConnectionFailed,
    FailedCommand,
    InvalidMessage,
    InvalidState,
    NotConnected,
)
from aiosonos.utils import create_ssl_context

from ._base import AbstractSonosApi

if TYPE_CHECKING:
    from collections.abc import Callable

    from aiohttp import ClientSession

    from aiosonos.api.models import GroupCoordinatorChanged

    from .namespaces._base import UnsubscribeCallbackType

    GroupCoordinatorChangedCallbackType = Callable[[str, GroupCoordinatorChanged], None]

API_VERSION = 1
# seconds to wait for a player's reply; a group command may never get one
COMMAND_TIMEOUT = 10
GROUP_COORDINATOR_CHANGED_EVENT = "groupCoordinatorChanged"


class SonosLocalWebSocketsApi(AbstractSonosApi):
    """Manage a Sonos Speaker using the local websockets api."""

    def __init__(
        self,
        websocket_url: str,
        aiohttp_session: ClientSession,
    ) -> None:
        """Initialize the Sonos API Connection to a local player's websocket."""
        super().__init__()
        self._aiohttp_session = aiohttp_session
        self.websocket_url = websocket_url
        self._ws_client: ClientWebSocketResponse | None = None
        self._result_futures: dict[str, asyncio.Future] = {}
        self._sends_in_flight: set[asyncio.Task[None]] = set()
        self._group_coordinator_listeners: list[GroupCoordinatorChangedCallbackType] = []

    @property
    def connected(self) -> bool:
        """Return if we're currently connected."""
        return self._ws_client is not None and not self._ws_client.closed

    def subscribe_group_coordinator_changed(
        self,
        callback: GroupCoordinatorChangedCallbackType,
    ) -> UnsubscribeCallbackType:
        """
        Listen for groupCoordinatorChanged events (global namespace).

        The player sends these to the subscribers of a group's namespaces, without
        a subscribe command of their own.

        :param callback: Called with the group id from the event header and the
            event body.
        :return: Handle to stop listening.
        """

        # one listener object per call, so the handle stops only its own registration
        # even when the same callback is registered twice
        def _listener(group_id: str, event_data: GroupCoordinatorChanged) -> None:
            # events are delivered a tick after they arrive: not to a listener stopped since
            if _listener in self._group_coordinator_listeners:
                callback(group_id, event_data)

        self._group_coordinator_listeners.append(_listener)

        def _unsubscribe() -> None:
            with suppress(ValueError):
                self._group_coordinator_listeners.remove(_listener)

        return _unsubscribe

    async def send_command(
        self,
        namespace: str,
        command: str,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Send a command and get a response.

        Raises CommandTimeout when the player does not reply within COMMAND_TIMEOUT seconds.
        """
        if self._sends_in_flight:
            # a command sent without waiting goes out first: commands reach the player
            # in the order they were sent (an unsubscribe before the next subscribe)
            await asyncio.wait(list(self._sends_in_flight))
        if not self.connected or not self._loop:
            raise InvalidState("Not connected")

        command_message = CommandMessage(
            namespace=f"{namespace}:{API_VERSION}",
            command=command,
            cmdId=uuid.uuid4().hex,
            # path params are passed as kwargs
            **kwargs,
        )
        future: asyncio.Future[Any] = self._loop.create_future()
        self._result_futures[command_message["cmdId"]] = future
        try:
            # body params are passed as options
            await self._send_message([command_message, options or {}])
            async with asyncio.timeout(COMMAND_TIMEOUT):
                return await future
        except TimeoutError:
            full_command = f"{namespace}:{command}"
            raise CommandTimeout(full_command, COMMAND_TIMEOUT) from None
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
        task = self.create_task(self._send_message([command_message, options or {}]))
        self._sends_in_flight.add(task)
        task.add_done_callback(self._sends_in_flight.discard)

    async def start_listening(self) -> None:
        """Connect (if needed) and start listening to incoming messages from the server."""
        if not self.connected:
            await self.connect()

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
                ssl=create_ssl_context(),
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

    def _handle_incoming_message(
        self,
        raw: tuple[ResultMessage, dict[str, Any]],
    ) -> None:
        """
        Handle incoming message.

        Run all async tasks in a wrapper to log appropriately.
        """
        msg, msg_data = raw

        # handle error message
        if "errorCode" in msg_data:
            if "cmdId" in msg:
                if (future := self._pending_future(msg["cmdId"])) is not None:
                    future.set_exception(
                        FailedCommand(msg_data["errorCode"], msg_data.get("reason")),
                    )
                return
            # unsolicited error event, sent to a namespace subscription
            self.logger.debug("Received error event: %s: %s", msg, msg_data)
            if msg.get("type") == self._playback.error_event_type:
                self.create_task(self._playback._handle_error_event(msg, msg_data))  # noqa: SLF001
            elif msg.get("type") == self._playback_session.error_event_type:
                self.create_task(
                    self._playback_session._handle_error_event(msg, msg_data)  # noqa: SLF001
                )
            return

        # handle command result message
        if "success" in msg:
            if (future := self._pending_future(msg["cmdId"])) is not None:
                if msg["success"]:
                    future.set_result(msg_data)
                else:
                    # e.g. a groupCoordinatorChanged body, which carries no errorCode
                    future.set_exception(FailedCommand(msg_data.get("_objectType", "unknown")))
            return

        # handle EventMessage
        if (event_type := msg.get("type")) == GROUP_COORDINATOR_CHANGED_EVENT:
            group_id = msg.get("groupId")
            if not isinstance(group_id, str) or not group_id:
                self.logger.debug("Received %s without groupId: %s", event_type, msg)
                return
            assert self._loop is not None  # set when listening started
            event_data = cast("GroupCoordinatorChanged", msg_data)
            for listener in list(self._group_coordinator_listeners):
                self._loop.call_soon(listener, group_id, event_data)
            return
        if event_type:
            # handle namespace specific events
            for namespace in (
                self._audio_clip,
                self._groups,
                self._group_volume,
                self._playback_metadata,
                self._playback_session,
                self._playback,
                self._player_volume,
            ):
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

    def _pending_future(self, cmd_id: str) -> asyncio.Future[Any] | None:
        """Return the future still waiting for the reply to a command (if any)."""
        future = self._result_futures.get(cmd_id)
        if future is None or future.done():
            # a command that timed out is cancelled before its slot is released,
            # so a reply arriving in between finds a future that is already done
            return None
        return future

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
            raise InvalidMessage(err_msg) from err
        except ValueError as err:
            raise InvalidMessage("Received invalid JSON.") from err

        if self.logger.isEnabledFor(LOG_LEVEL_VERBOSE):
            self.logger.log(
                LOG_LEVEL_VERBOSE,
                "Received message:\n%s\n",
                pprint.pformat(ws_msg),
            )

        return msg

    async def _send_message(
        self,
        message: tuple[CommandMessage, dict[str, Any]],
    ) -> None:
        """
        Send a message to the server.

        Raises NotConnected if client not connected.
        """
        if not self.connected:
            raise NotConnected

        if self.logger.isEnabledFor(LOG_LEVEL_VERBOSE):
            self.logger.log(
                LOG_LEVEL_VERBOSE,
                "Publishing message:\n%s\n",
                pprint.pformat(message),
            )

        assert self._ws_client
        # sonos messages are always an array of 2 dict objects
        assert isinstance(message, list)

        await self._ws_client.send_bytes(orjson.dumps(message))
