"""Representation of a Sonos Player."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiosonos.api.models import AudioClipLEDBehavior, AudioClipType
from aiosonos.const import EventType, PlayerEvent

if TYPE_CHECKING:
    from aiosonos.group import SonosGroup

    from .api.models import Player as PlayerData
    from .api.models import PlayerVolume as PlayerVolumeData
    from .client import SonosLocalApiClient


class SonosPlayer:
    """Representation of a Sonos Player."""

    _active_group: SonosGroup | None

    def __init__(self, client: SonosLocalApiClient, data: PlayerData) -> None:
        """Handle initialization."""
        self.client = client
        self._data = data
        self._volume_data: PlayerVolumeData | None = None
        for group in client.groups:
            if group.coordinator_id == self.id or self.id in group.player_ids:
                self._active_group = group
                break
        else:
            self._active_group = None

    async def async_init(self) -> None:
        """Handle Async initialization."""
        # grab volume data and setup subscription
        self._volume_data = await self.client.api.player_volume.get_volume(self.id)
        await self.client.api.player_volume.subscribe(
            self.id,
            self._handle_volume_update,
        )

    @property
    def name(self) -> str:
        """Return the name of the player."""
        return self._data["name"]

    @property
    def id(self) -> str:
        """Return the player id."""
        return self._data["id"]

    @property
    def icon(self) -> str:
        """Return the icon."""
        return self._data.get("icon", "")

    @property
    def volume_level(self) -> int | None:
        """Return the current volume level of the player."""
        return self._volume_data.get("volume")

    @property
    def volume_muted(self) -> bool | None:
        """Return the current mute state of the player."""
        return self._volume_data.get("muted")

    @property
    def has_fixed_volume(self) -> bool | None:
        """Return if this player has a fixed volume level."""
        return self._volume_data.get("fixed")

    @property
    def group(self) -> SonosGroup | None:
        """Return the active group."""
        return self._active_group

    @property
    def is_coordinator(self) -> bool:
        """Return if this player is the coordinator of the active group it belongs to."""
        if not self.group:
            return False
        return self.group.coordinator_id == self.id

    @property
    def is_passive(self) -> bool:
        """Return if this player is the NOT a coordinator but a passive member of a group."""
        if not self.group:
            return False
        return self.group.coordinator_id != self.id

    @property
    def group_members(self) -> list[str]:
        """Return the player ids of the group members."""
        if not self.group:
            return []
        return self.group.player_ids

    async def set_volume(
        self,
        volume: int | None = None,
        muted: bool | None = None,
    ) -> None:
        """Set the volume of the player."""
        await self.client.api.player_volume.set_volume(self.id, volume, muted)

    async def duck(self, duration_millis: int | None = None) -> None:
        """Duck the volume of the player."""
        await self.client.api.player_volume.duck(self.id, duration_millis)

    async def leave_group(self) -> None:
        """Leave the active group this player is joined to (if any)."""
        if not self.group:
            return
        await self.client.api.groups.modify_group_members(
            self.group.id,
            player_ids_to_add=[],
            player_ids_to_remove=[self.id],
        )

    async def join_group(self, group_id: str) -> None:
        """Join a group."""
        await self.client.api.groups.modify_group_members(
            group_id,
            player_ids_to_add=[self.id],
            player_ids_to_remove=[],
        )

    async def play_audio_clip(
        self,
        url: str,
        volume: int | None = None,
        name: str | None = None,
    ) -> None:
        """Play an audio clip (announcement) on the player."""
        await self.client.api.audio_clip.load_audio_clip(
            self.id,
            name=name or "aiosonos",
            app_id="aiosonos",
            stream_url=url,
            volume=volume,
            clip_type=AudioClipType.CUSTOM,
            clip_led_behavior=AudioClipLEDBehavior.WHITE_LED_QUICK_BREATHING,
        )

    def update_data(self, data: PlayerData) -> None:
        """Update the player data."""
        self.check_active_group()
        if data == self._data:
            return
        for key, value in data.items():
            self._data[key] = value
        self.client.signal_event(
            PlayerEvent(
                EventType.PLAYER_UPDATED,
                data.get("id", self.id),
                self,
            ),
        )

    def check_active_group(self) -> None:
        """Check/set the active group of this player."""
        prev_group_id = self._active_group.id if self._active_group else None
        for group in self.client.groups:
            if group.coordinator_id == self.id or self.id in group.player_ids:
                self._active_group = group
                break
        if prev_group_id == self.group.id:
            return
        self.client.signal_event(
            PlayerEvent(
                EventType.PLAYER_UPDATED,
                self.id,
                self,
            ),
        )

    def _handle_volume_update(self, data: PlayerVolumeData) -> None:
        """Handle volume update."""
        if data == self._volume_data:
            return
        self._volume_data = data
        self.client.signal_event(
            PlayerEvent(
                EventType.PLAYER_UPDATED,
                self.id,
                self,
            ),
        )
