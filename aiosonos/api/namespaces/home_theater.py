"""Handle HomeTheater related endpoints for Sonos."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import SonosNameSpace

if TYPE_CHECKING:
    from aiosonos.api.models import HomeTheaterOptions, TvPowerState


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

    async def get_options(
        self,
        player_id: str,
    ) -> HomeTheaterOptions:
        """Get the home theater options (night mode, speech enhancement, etc.)."""
        return await self.api.send_command(
            namespace=self.namespace,
            command="getOptions",
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

    async def get_tv_power_state(
        self,
        player_id: str,
    ) -> dict[str, Any]:
        """
        Get the power state of the TV connected over HDMI-CEC.

        Raises FailedCommand on players without HDMI-CEC.
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="getTvPowerState",
            playerId=player_id,
        )

    async def set_tv_power_state(
        self,
        player_id: str,
        tv_power_state: TvPowerState,
    ) -> None:
        """Turn the TV connected over HDMI-CEC on or to standby."""
        await self.api.send_command(
            namespace=self.namespace,
            command="setTvPowerState",
            playerId=player_id,
            options={"tvPowerState": tv_power_state},
        )
