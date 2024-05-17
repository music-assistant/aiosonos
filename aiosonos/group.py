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

from typing import TYPE_CHECKING

from aiosonos.const import EventType, GroupEvent

if TYPE_CHECKING:
    from aiosonos.api.models import GroupVolume as GroupVolumeData
    from aiosonos.api.models import PlayBackState
    from aiosonos.api.models import PlaybackStatus as PlaybackStatusData
    from aiosonos.api.models import PlayModes as PlayModesData

    from .api.models import Group as GroupData
    from .api.models import PlaybackActions as PlaybackActionsData
    from .client import SonosApiClient


class SonosGroup:
    """Representation of a Sonos Group."""

    _playback_data: PlaybackStatusData
    _volume_data: GroupVolumeData
    _playback_actions: PlaybackActions
    _play_modes: PlayModes

    def __init__(self, client: SonosApiClient, data: GroupData) -> None:
        """Handle initialization."""
        self.client = client
        self._data = data

    async def async_init(self) -> None:
        """Handle Async initialization."""
        # grab playback data and setup subscription
        self._playback_data = await self.client.api.playback.get_playback_status(self.id)
        self._volume_data = await self.client.api.group_volume.get_volume(self.id)
        self._playback_actions = PlaybackActions(self._playback_data["availablePlaybackActions"])
        self._play_modes = PlayModes(self._playback_data["playModes"])
        await self.client.api.playback.subscribe(self.id, self._handle_playback_status_update)
        await self.client.api.group_volume.subscribe(self.id, self._handle_volume_update)

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
        return self._playback_data.get("playbackState") or self._data["playbackState"]

    @property
    def player_ids(self) -> list[str]:
        """Return ths id's of this group's members."""
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
    def play_modes(self) -> PlayModes:
        """Return the play modes of this group."""
        return self._play_modes

    async def play(self) -> None:
        """Send play command to group."""
        await self.client.api.playback.play(self.id)

    async def pause(self) -> None:
        """Send pause command to group."""
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
            crossfade,
            repeat,
            repeat_one,
            shuffle,
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
        if data == self._playback_data:
            return
        self._playback_data = data
        self._playback_actions.raw_data.update(data["availablePlaybackActions"])
        self._play_modes.raw_data.update(data["playModes"])
        self.client.signal_event(
            GroupEvent(
                EventType.GROUP_UPDATED,
                data["id"],
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
                data["id"],
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
