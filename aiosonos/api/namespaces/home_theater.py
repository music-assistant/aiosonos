"""Handle HomeTheater related endpoints for Sonos."""

from __future__ import annotations

from ._base import SonosNameSpace


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
