"""Handle Playback related endpoints for Sonos."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiosonos.api.models import LoadContentRequest, PlaybackError, PlaybackStatus, PlayModes

from ._base import SonosNameSpace, SubscribeCallbackType, UnsubscribeCallbackType

if TYPE_CHECKING:
    from aiosonos.api import SonosLocalWebSocketsApi


class PlaybackNameSpace(SonosNameSpace):
    """PlaybackNameSpace Namespace handlers."""

    namespace = "playback"
    event_type = "playbackStatus"
    error_event_type = "playbackError"
    _event_model = PlaybackStatus
    _event_key = "groupId"

    def __init__(self, api: SonosLocalWebSocketsApi) -> None:
        """Handle Initialization."""
        super().__init__(api)
        self._error_listeners: dict[str, SubscribeCallbackType[PlaybackError]] = {}

    async def get_playback_status(
        self,
        group_id: str,
    ) -> PlaybackStatus:
        """
        Send getPlaybackStatus command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-getplaybackstatus-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="getPlaybackStatus",
            groupId=group_id,
        )

    async def load_line_in(
        self,
        group_id: str,
        device_id: str | None = None,
        play_on_completion: bool = False,  # noqa: FBT002
    ) -> None:
        """
        Send getPlaybackStatus command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-loadlinein-groupid
        """
        options = {}
        if device_id is not None:
            options["deviceId"] = device_id
        if play_on_completion is not None:
            options["playOnCompletion"] = play_on_completion
        await self.api.send_command(
            namespace=self.namespace,
            command="loadLineIn",
            groupId=group_id,
            options=options,
        )

    async def load_content(
        self,
        group_id: str,
        content: LoadContentRequest,
    ) -> None:
        """Load content on the existing group's queue."""
        await self.api.send_command(
            namespace=self.namespace, command="loadContent", groupId=group_id, options=content
        )

    async def pause(
        self,
        group_id: str,
    ) -> None:
        """
        Send pause command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-pause-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="pause",
            groupId=group_id,
        )

    async def play(
        self,
        group_id: str,
    ) -> None:
        """
        Send play command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-play-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="play",
            groupId=group_id,
        )

    async def set_play_modes(
        self,
        group_id: str,
        repeat: bool | None = None,
        repeat_one: bool | None = None,
        shuffle: bool | None = None,
        crossfade: bool | None = None,
    ) -> None:
        """
        Send getPlaybackStatus command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-setplaymodes-groupid
        """
        play_modes = PlayModes()
        if repeat is not None:
            play_modes["repeat"] = repeat
        if repeat_one is not None:
            play_modes["repeatOne"] = repeat_one
        if shuffle is not None:
            play_modes["shuffle"] = shuffle
        if crossfade is not None:
            play_modes["crossfade"] = crossfade
        await self.api.send_command(
            namespace=self.namespace,
            command="setPlayModes",
            groupId=group_id,
            options={
                "playModes": play_modes,
            },
        )

    async def seek(
        self,
        group_id: str,
        position_millis: int,
        item_id: str | None = None,
    ) -> None:
        """
        Send seek command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-seek-groupid
        """
        options = {
            "positionMillis": position_millis,
        }
        if item_id is not None:
            options["itemId"] = item_id
        await self.api.send_command(
            namespace=self.namespace,
            command="seek",
            groupId=group_id,
            options=options,
        )

    async def seek_relative(
        self,
        group_id: str,
        delta_millis: int,
        item_id: str | None = None,
    ) -> None:
        """
        Send seekRelative command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-seekrelative-groupid
        """
        options = {
            "deltaMillis": delta_millis,
        }
        if item_id is not None:
            options["itemId"] = item_id
        await self.api.send_command(
            namespace=self.namespace,
            command="seekRelative",
            groupId=group_id,
            options=options,
        )

    async def skip_to_next_track(
        self,
        group_id: str,
    ) -> None:
        """
        Send skipToNextTrack command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-skiptonexttrack-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="skipToNextTrack",
            groupId=group_id,
        )

    async def skip_to_previous_track(
        self,
        group_id: str,
    ) -> None:
        """
        Send skipToPreviousTrack command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-skiptoprevioustrack-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="skipToPreviousTrack",
            groupId=group_id,
        )

    async def toggle_play_pause(
        self,
        group_id: str,
    ) -> None:
        """
        Send togglePlayPause command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playback-toggleplaypause-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="togglePlayPause",
            groupId=group_id,
        )

    async def subscribe(
        self,
        group_id: str,
        callback: SubscribeCallbackType[PlaybackStatus],
        error_callback: SubscribeCallbackType[PlaybackError] | None = None,
    ) -> UnsubscribeCallbackType:
        """
        Subscribe to events in the Playback namespace for given group.

        The optional error_callback receives playbackError events,
        sent when the group fails to play an item.

        Returns handle to unsubscribe.

        Reference:
        https://docs.sonos.com/reference/playback-subscribe-groupid
        """
        unsubscribe = await self._handle_subscribe(group_id, callback)
        if error_callback is None:
            self._error_listeners.pop(group_id, None)
        else:
            self._error_listeners[group_id] = error_callback

        def _unsubscribe() -> None:
            self._error_listeners.pop(group_id, None)
            unsubscribe()

        return _unsubscribe

    async def _handle_error_event(self, event: dict[str, Any], event_data: PlaybackError) -> None:
        """Forward a playbackError event to the subscribed error listener."""
        if handler := self._error_listeners.get(event[self._event_key]):
            handler(event_data)
