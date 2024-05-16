"""Representation of a Sonos Player."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiosonos.const import EventType, PlayerEvent

if TYPE_CHECKING:
    from .api.models import Player as PlayerData
    from .api.models import PlayerVolume as PlayerVolumeData
    from .client import SonosApiClient


class SonosPlayer:
    """Representation of a Sonos Player."""

    def __init__(self, client: SonosApiClient, data: PlayerData) -> None:
        """Handle initialization."""
        self.client = client
        self._data = data
        self._volume_data: PlayerVolumeData | None = None

    async def async_init(self) -> None:
        """Handle Async initialization."""
        # grab volume data and setup subscription
        self._volume_data = await self.client.api.player_volume.get_volume(self.id)
        await self.client.api.player_volume.subscribe(self.id, self._handle_volume_update)

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
        return self._data["icon"]

    @property
    def volume_level(self) -> int | None:
        """Return the current volume level of the player."""
        return self._volume_data.get("volume")

    @property
    def volume_muted(self) -> bool | None:
        """Return the current mute state of the player."""
        return self._volume_data.get("mute")

    @property
    def has_fixed_volume(self) -> bool | None:
        """Return if this player has a fixed volume level."""
        return self._volume_data.get("fixed")

    def update_data(self, data: PlayerData) -> None:
        """Update the player data."""
        if data == self._data:
            return
        for key, value in data.items():
            self._data[key] = value
        self.client.signal_event(
            PlayerEvent(
                EventType.PLAYER_UPDATED,
                data["id"],
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
