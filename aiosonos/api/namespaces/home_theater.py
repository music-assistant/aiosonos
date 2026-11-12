"""Handle HomeTheater related endpoints for Sonos."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._base import SonosNameSpace

if TYPE_CHECKING:
    from aiosonos.api.models import HomeTheaterOptions


class HomeTheaterNameSpace(SonosNameSpace):
    """HomeTheater Namespace handlers."""

    namespace = "homeTheater"
    event_type = "homeTheaterStatus"
    _event_model = None  # TODO: Add model
    _event_key = "playerId"

    async def load_home_theater_playback(
        self,
        player_id: str,
    ) -> None:
        """
        Send loadHomeTheaterPlayback command to player.

        Note that this command is not yet documented in the api docs and
        has been reverse engineered from the Sonos Web Controller.
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="loadHomeTheaterPlayback",
            playerId=player_id,
        )

    async def set_options(
        self,
        player_id: str,
        options: dict[str, bool | int],
    ) -> HomeTheaterOptions:
        """
        Set home theater options and return them as the player applied them.

        A player silently ignores an option it does not support.

        :param player_id: The player to set the options on.
        :param options: The homeTheaterOptions fields to change, e.g. {"nightMode": True}.
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="setOptions",
            playerId=player_id,
            options=options,
        )
