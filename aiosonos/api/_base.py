"""Base model for a Sonos API Controller."""

from __future__ import annotations

import logging
import uuid
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Self

from aiosonos.api.namespaces.audio_clip import AudioClipNameSpace
from aiosonos.api.namespaces.group_volume import GroupVolumeNameSpace
from aiosonos.api.namespaces.groups import GroupsNameSpace
from aiosonos.api.namespaces.playback import PlaybackNameSpace
from aiosonos.api.namespaces.playback_metadata import PlaybackMetadataNameSpace
from aiosonos.api.namespaces.playback_session import PlaybackSessionNameSpace
from aiosonos.api.namespaces.player_volume import PlayerVolumeNameSpace

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable
    from types import TracebackType


class AbstractSonosApi:
    """Base abstraction for a Sonos API."""

    def __init__(
        self,
    ) -> None:
        """Initialize."""
        self.logger = logging.getLogger(__package__)
        self._stop_called: bool = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_clip = AudioClipNameSpace(self)
        self._groups = GroupsNameSpace(self)
        self._group_volume = GroupVolumeNameSpace(self)
        self._playback = PlaybackNameSpace(self)
        self._playback_metadata = PlaybackMetadataNameSpace(self)
        self._playback_session = PlaybackSessionNameSpace(self)
        self._player_volume = PlayerVolumeNameSpace(self)
        self._tracked_tasks: dict[str, asyncio.Task] = {}

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Return if we're currently connected."""

    @property
    def audio_clip(self) -> AudioClipNameSpace:
        """Return AudioClip namespace handler."""
        return self._audio_clip

    @property
    def groups(self) -> GroupsNameSpace:
        """Return Groups namespace handler."""
        return self._groups

    @property
    def group_volume(self) -> GroupVolumeNameSpace:
        """Return GroupVolume namespace handler."""
        return self._group_volume

    @property
    def playback(self) -> PlaybackNameSpace:
        """Return PlayBack namespace handler."""
        return self._playback

    @property
    def playback_metadata(self) -> PlaybackMetadataNameSpace:
        """Return PlaybackMetadata namespace handler."""
        return self._playback_metadata

    @property
    def playback_session(self) -> PlaybackSessionNameSpace:
        """Return PlaybackSession namespace handler."""
        return self._playback_session

    @property
    def player_volume(self) -> PlayerVolumeNameSpace:
        """Return PlayerVolume namespace handler."""
        return self._player_volume

    @abstractmethod
    async def send_command(
        self,
        namespace: str,
        command: str,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Send a command and get a response."""

    @abstractmethod
    def send_command_no_wait(
        self,
        namespace: str,
        command: str,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a command without waiting for the response."""

    @abstractmethod
    async def start_listening(self, init_ready: asyncio.Event | None = None) -> None:
        """Connect (if needed) and start listening to incoming messages from the server."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the server/api."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect the client and cleanup."""

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
