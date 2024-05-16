"""Representation of a Sonos Group."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiosonos.const import EventType, GroupEvent

if TYPE_CHECKING:
    from .api.models import Group as GroupData
    from .api.models import PlayBackState
    from .client import SonosApiClient


class SonosGroup:
    """Representation of a Sonos Group."""

    def __init__(self, client: SonosApiClient, data: GroupData) -> None:
        """Handle initialization."""
        self.client = client
        self._data = data

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
        return self._data["playbackState"]

    @property
    def player_ids(self) -> list[str]:
        """Return ths id's of this group's members."""
        return self._data["playerIds"]

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
