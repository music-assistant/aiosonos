"""Handle Settings related endpoints for Sonos."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._base import SonosNameSpace

if TYPE_CHECKING:
    from aiosonos.api.models import PlayerSettings


class SettingsNameSpace(SonosNameSpace):
    """Settings Namespace handlers."""

    namespace = "settings"
    # carries only settings group names and timestamps, no values
    event_type = "settingsChanged"
    _event_model = None
    _event_key = "playerId"

    async def get_player_settings(
        self,
        player_id: str,
    ) -> PlayerSettings:
        """
        Get the player's settings (EQ, home theater options, etc.).

        The local websocket refuses setPlayerSettings, so these are read-only here:
        home theater options are set with the homeTheater namespace, EQ over UPnP.
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="getPlayerSettings",
            playerId=player_id,
        )
