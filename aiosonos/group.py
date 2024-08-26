"""
Representation of a Sonos Group.

Sonos players are always in groups, even if the group has only one player.
All players in a group play the same audio in synchrony.
Users can easily move players from one group to another without interrupting playback.
Transport controls, such as play, pause, skip to next track, and skip to previous track,
target groups rather than individual players.
Players must be part of the same household to be part of a group.

Reference: https://docs.sonos.com/docs/control
"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import TYPE_CHECKING

from aiosonos.api.models import (
    ContainerType,
    MetadataStatus,
    MusicService,
    PlayBackState,
)
from aiosonos.api.models import GroupVolume as GroupVolumeData
from aiosonos.api.models import PlaybackStatus as PlaybackStatusData
from aiosonos.api.models import PlayModes as PlayModesData
from aiosonos.const import EventType, GroupEvent
from aiosonos.exceptions import FailedCommand

from .api.models import PlaybackActions as PlaybackActionsData

if TYPE_CHECKING:
    from aiosonos.api.models import Container, SessionStatus, Track

    from .api.models import Group as GroupData
    from .client import SonosLocalApiClient


class SonosGroup:
    """Representation of a Sonos Group."""

    def __init__(self, client: SonosLocalApiClient, data: GroupData) -> None:
        """Handle initialization."""
        self.client = client
        self.active_session_id: str | None = None
        self._data = data
        # to prevent race conditions at startup/init,
        # we set some default values for the status dicts here
        self._play_modes = PlayModes({})
        self._volume_data = GroupVolumeData(
            objectType="groupVolume", fixed=False, volume=0, mute=False
        )
        self._playback_actions = playback_actions = PlaybackActionsData(
            canCrossfade=False,
            canPause=False,
            canPlay=False,
            canSeek=False,
            canSkipBackward=False,
            canSkipForward=False,
            canStop=False,
        )
        self._playback_status_data: PlaybackStatusData = PlaybackStatusData(
            objectType="playbackStatus",
            availablePlaybackActions=playback_actions,
            isDucking=False,
            playbackState=PlayBackState.PLAYBACK_STATE_IDLE,
            playModes=PlayModesData(),
            positionMillis=0,
            previousPositionMillis=0,
        )
        self._playback_metadata_data: MetadataStatus = MetadataStatus(objectType="metadataStatus")
        self._playback_status_last_updated: float = 0.0
        self._unsubscribe_callbacks = []

    def cleanup(self) -> None:
        """Handle cleanup on deletion."""
        for unsubscribe_callback in self._unsubscribe_callbacks:
            unsubscribe_callback()
        self._unsubscribe_callbacks = []

    async def async_init(self) -> None:
        """Handle Async initialization."""
        # grab playback data and setup subscription
        try:
            self._volume_data = await self.client.api.group_volume.get_volume(self.id)
            self._playback_status_data = await self.client.api.playback.get_playback_status(self.id)
            self._playback_status_last_updated = time.time()
            self._playback_actions = PlaybackActions(
                self._playback_status_data["availablePlaybackActions"],
            )
            self._play_modes = PlayModes(self._playback_status_data["playModes"])
            self._playback_metadata_data = (
                await self.client.api.playback_metadata.get_metadata_status(
                    self.id,
                )
            )
            self._unsubscribe_callbacks = [
                await self.client.api.playback.subscribe(
                    self.id,
                    self._handle_playback_status_update,
                ),
                await self.client.api.group_volume.subscribe(
                    self.id,
                    self._handle_volume_update,
                ),
                await self.client.api.playback_metadata.subscribe(
                    self.id,
                    self._handle_metadata_status_update,
                ),
            ]
        except FailedCommand as err:
            if err.error_code == "groupCoordinatorChanged":
                # retrieving group details is not possible for remote groups when
                # connected to a player's local websocket.
                self._volume_data = {}
                self._playback_status_data = {}
                self._playback_actions = PlaybackActions({})
                self._play_modes = PlayModes({})
                self._playback_metadata_data = {}
                return
            raise
        else:
            self.client.signal_event(
                GroupEvent(
                    EventType.GROUP_ADDED,
                    self.id,
                    self,
                ),
            )

    @property
    def name(self) -> str:
        """Return the name of the group."""
        return self._data["name"]

    @property
    def id(self) -> str:
        """Return the group id."""
        return self._data["id"]

    @property
    def coordinator_id(self) -> str:
        """Return the coordinator's player Id (group leader)."""
        return self._data["coordinatorId"]

    @property
    def playback_state(self) -> PlayBackState:
        """Return the playback state of this group."""
        return (
            self._playback_status_data.get("playbackState")
            or self._data.get("playbackState")
            or PlayBackState.PLAYBACK_STATE_IDLE
        )

    @property
    def player_ids(self) -> list[str]:
        """Return the id's of this group's members."""
        return self._data["playerIds"]

    @property
    def area_ids(self) -> list[str]:
        """Return the area id's of this group (if any)."""
        return self._data.get("areaIds", [])

    @property
    def playback_actions(self) -> PlaybackActions:
        """Return the playback actions of this group."""
        return self._playback_actions

    @property
    def playback_metadata(self) -> MetadataStatus:
        """Return the MetadataStatus of this group."""
        return self._playback_metadata_data

    @property
    def position(self) -> float:
        """Return the (corrected) current position in (fractions of) seconds."""
        if self.playback_state == PlayBackState.PLAYBACK_STATE_PLAYING:
            return self._playback_status_data.get("positionMillis", 0) / 1000 + (
                time.time() - self._playback_status_last_updated
            )
        return self._playback_status_data.get("positionMillis", 0) / 1000

    @property
    def is_ducking(self) -> bool:
        """Return if the group's volume is currently ducked."""
        return self._playback_status_data.get("isDucking", False)

    @property
    def play_modes(self) -> PlayModes:
        """Return the play modes of this group."""
        return self._play_modes

    @property
    def container_type(self) -> ContainerType | None:
        """Return the container_type of the active source of this group (if any)."""
        if not (container := self._playback_metadata_data.get("container")):
            return None
        if container_type := container.get("type"):
            if container_type in ContainerType:
                return ContainerType(container_type)
            # return the raw string value if it's not a known container type
            return container_type
        return None

    @property
    def active_service(self) -> MusicService | None:
        """Return the active service of the active source of this group (if any)."""
        if not (container := self._playback_metadata_data.get("container")):
            return None
        if (container_id := container.get("id")) and (service_id := container_id.get("serviceId")):
            if service_id in MusicService:
                return MusicService(service_id)
            # return the raw string value if it's not a known container type
            return service_id
        return None

    async def play(self) -> None:
        """Send play command to group."""
        await self.client.api.playback.play(self.id)

    async def pause(self) -> None:
        """Send pause command to group."""
        await self.client.api.playback.pause(self.id)

    async def stop(self) -> None:
        """Send stop command to group."""
        if session_id := self.active_session_id:
            self.active_session_id = None
            with suppress(FailedCommand):
                await self.client.api.playback_session.suspend(session_id)
                return
        # always fall back to pause if no session is active
        # TODO: figure out if there is some better way to figure out
        # the active session id to suspend it.
        await self.client.api.playback.pause(self.id)

    async def toggle_play_pause(self) -> None:
        """Send play/pause command to group."""
        await self.client.api.playback.toggle_play_pause(self.id)

    async def skip_to_next_track(self) -> None:
        """Send skipToNextTrack command to group."""
        await self.client.api.playback.skip_to_next_track(self.id)

    async def skip_to_previous_track(self) -> None:
        """Send skipToPreviousTrack command to group."""
        await self.client.api.playback.skip_to_previous_track(self.id)

    async def set_play_modes(
        self,
        crossfade: bool | None = None,
        repeat: bool | None = None,
        repeat_one: bool | None = None,
        shuffle: bool | None = None,
    ) -> None:
        """Send setPlayModes command to group."""
        await self.client.api.playback.set_play_modes(
            self.id,
            crossfade=crossfade,
            repeat=repeat,
            repeat_one=repeat_one,
            shuffle=shuffle,
        )

    async def seek(self, position: int) -> None:
        """Send seek command to group."""
        await self.client.api.playback.seek(self.id, position)

    async def seek_relative(self, delta: int) -> None:
        """Send seekRelative command to group."""
        await self.client.api.playback.seek_relative(self.id, delta)

    async def load_line_in(
        self,
        device_id: str | None = None,
        play_on_completion: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        """
        Send loadLineIn command to group.

        Parameters:
        - device_id (Optional): Represents the line-in source,
        any player in the household that supports line-in.
        The default value is the local deviceId.
        This is the same as the player ID returned in the player object.

        - play_on_completion (Optional): If true, start playback after
        loading the line-in source. If false, the player loads the cloud queue,
        but requires the play command to begin.
        If not provided, the default value is false.
        """
        await self.client.api.playback.load_line_in(
            self.id,
            device_id=device_id,
            play_on_completion=play_on_completion,
        )

    async def modify_group_members(
        self,
        player_ids_to_add: list[str],
        player_ids_to_remove: list[str],
    ) -> None:
        """Modify the group's members."""
        await self.client.api.groups.modify_group_members(
            self.id,
            player_ids_to_add,
            player_ids_to_remove,
        )

    async def set_group_members(
        self,
        player_ids: list[str],
        area_ids: list[str] | None = None,
    ) -> None:
        """Set/replace the group's members."""
        await self.client.api.groups.set_group_members(self.id, player_ids, area_ids)

    async def create_playback_session(
        self,
        app_id: str = "com.aiosonos.playback",
        app_context: str = "1",
        account_id: str | None = None,
        custom_data: dict | None = None,
    ) -> SessionStatus:
        """Create a new Playback Session."""
        session = await self.client.api.playback_session.create_session(
            self.id,
            app_id,
            app_context,
            account_id,
            custom_data,
        )
        self.active_session_id = session["sessionId"]
        return session

    async def play_stream_url(self, url: str, metadata: Container) -> None:
        """Create a new playback session and start playing a single (radio) stream URL."""
        await self.create_playback_session()
        await self.client.api.playback_session.load_stream_url(
            self.active_session_id,
            stream_url=url,
            play_on_completion=True,
            station_metadata=metadata,
        )

    async def play_cloud_queue(
        self,
        queue_base_url: str,
        http_authorization: str | None = None,
        use_http_authorization_for_media: bool | None = None,
        item_id: str | None = None,
        queue_version: str | None = None,
        position_millis: int | None = None,
        track_metadata: Track | None = None,
    ) -> None:
        """
        Create a new playback session and start playing a (cloud) queue.

        For all options, see:
        https://docs.sonos.com/reference/playbacksession-loadcloudqueue-sessionid
        """
        if not self.active_session_id:
            await self.create_playback_session()
        await self.client.api.playback_session.load_cloud_queue(
            self.active_session_id,
            queue_base_url=queue_base_url,
            http_authorization=http_authorization,
            use_http_authorization_for_media=use_http_authorization_for_media,
            item_id=item_id,
            queue_version=queue_version,
            position_millis=position_millis,
            play_on_completion=True,
            track_metadata=track_metadata,
        )

    def update_data(self, data: GroupData) -> None:
        """Update the player data."""
        if data == self._data:
            return
        for key, value in data.items():
            self._data[key] = value
        self.client.signal_event(
            GroupEvent(
                EventType.GROUP_UPDATED,
                data["id"],
                self,
            ),
        )

    def _handle_playback_status_update(self, data: PlaybackStatusData) -> None:
        """Handle playbackStatus update."""
        if data == self._playback_status_data:
            return
        self._playback_status_data = data
        self._playback_status_last_updated = time.time()
        self._playback_actions.raw_data.update(data["availablePlaybackActions"])
        self._play_modes.raw_data.update(data["playModes"])
        self.client.signal_event(
            GroupEvent(
                EventType.GROUP_UPDATED,
                self.id,
                self,
            ),
        )

    def _handle_metadata_status_update(self, data: MetadataStatus) -> None:
        """Handle MetadataStatus update."""
        if data == self._playback_metadata_data:
            return
        self._playback_metadata_data = data
        self.client.signal_event(
            GroupEvent(
                EventType.GROUP_UPDATED,
                self.id,
                self,
            ),
        )

    def _handle_volume_update(self, data: GroupVolumeData) -> None:
        """Handle volume update."""
        if data == self._volume_data:
            return
        self._volume_data = data
        self.client.signal_event(
            GroupEvent(
                EventType.GROUP_UPDATED,
                self.id,
                self,
            ),
        )


class PlaybackActions:
    """Representation of the PlaybackActions on a Sonos Group."""

    def __init__(self, raw_data: PlaybackActionsData) -> None:
        """Handle initialization."""
        self.raw_data = raw_data

    @property
    def can_skip_forward(self) -> bool:
        """Return if the group can skip forward."""
        return self.raw_data.get("canSkipForward", False)

    @property
    def can_skip_backward(self) -> bool:
        """Return if the group can skip backward."""
        return self.raw_data.get("canSkipBackward", False)

    @property
    def can_play(self) -> bool:
        """Return if the group can play."""
        return self.raw_data.get("canPlay", False)

    @property
    def can_pause(self) -> bool:
        """Return if the group can pause."""
        return self.raw_data.get("canPause", False)

    @property
    def can_stop(self) -> bool:
        """Return if the group can stop."""
        return self.raw_data.get("canStop", False)


class PlayModes:
    """Representation of the PlayModes on a Sonos Group."""

    def __init__(self, raw_data: PlayModesData) -> None:
        """Handle initialization."""
        self.raw_data = raw_data

    @property
    def crossfade(self) -> bool | None:
        """Return if crossfade is enabled."""
        return self.raw_data.get("crossfade")

    @property
    def repeat(self) -> bool | None:
        """Return if repeat is enabled."""
        return self.raw_data.get("repeat")

    @property
    def repeat_one(self) -> bool | None:
        """Return if repeat one is enabled."""
        return self.raw_data.get("repeatOne")

    @property
    def shuffle(self) -> bool | None:
        """Return if shuffle is enabled."""
        return self.raw_data.get("shuffle")
