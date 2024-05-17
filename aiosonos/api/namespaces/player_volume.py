"""Handle PlayerVolume related endpoints for Sonos."""

from __future__ import annotations

from aiosonos.api.models import PlayerVolume

from ._base import SonosNameSpace, SubscribeCallbackType, UnsubscribeCallbackType


class PlayerVolumeNameSpace(SonosNameSpace):
    """PlayerVolume Namespace handlers."""

    namespace = "playerVolume"
    event_type = "playerVolume"
    _event_model = PlayerVolume
    _event_key = "playerId"

    async def set_volume(
        self,
        player_id: str,
        volume: int | None = None,
        muted: bool | None = None,
    ) -> None:
        """
        Send setVolume command to set the player's volume and mute state.

        Note that when connected to a local speaker's websocket,
        the player id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playervolume-setvolume-playerid
        """
        options = {}
        if volume is not None:
            options["volume"] = volume
        if muted is not None:
            options["muted"] = muted
        await self.api.send_command(
            namespace=self.namespace,
            command="setVolume",
            playerId=player_id,
            options=options,
        )

    async def get_volume(
        self,
        player_id: str,
    ) -> PlayerVolume:
        """
        Get the player's volume and mute state.

        Note that when connected to a local speaker's websocket,
        the player id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playervolume-getvolume-playerid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="getVolume",
            playerId=player_id,
        )

    async def duck(
        self,
        player_id: str,
        duration_millis: int | None = None,
    ) -> None:
        """
        Send volume duck command to player.

        Note that when connected to a local speaker's websocket,
        the player id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playervolume-duck-playerid
        """
        await self.api.send_command(
            namespace=self.namespace,
            command="duck",
            playerId=player_id,
            options={"durationMillis": duration_millis} if duration_millis else None,
        )

    async def set_mute(
        self,
        player_id: str,
        muted: bool,  # noqa: FBT001
    ) -> None:
        """
        Send the setMute command to set the player's mute state.

        Note that when connected to a local speaker's websocket,
        the player id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playervolume-setmute-playerid
        """
        await self.api.send_command(
            namespace=self.namespace,
            command="setMute",
            playerId=player_id,
            options={"muted": muted},
        )

    async def set_relative_volume(
        self,
        player_id: str,
        volume_delta: int | None = None,
        muted: bool | None = None,
    ) -> None:
        """
        Send setRelativeVolume command to set the player's volume and mute state.

        Note that when connected to a local speaker's websocket,
        the player id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playervolume-setvolume-playerid
        """
        options = {}
        if volume_delta is not None:
            options["volumeDelta"] = volume_delta
        if muted is not None:
            options["muted"] = muted
        await self.api.send_command(
            namespace=self.namespace,
            command="setRelativeVolume",
            playerId=player_id,
            options=options,
        )

    async def subscribe(
        self,
        player_id: str,
        callback: SubscribeCallbackType,
    ) -> UnsubscribeCallbackType:
        """
        Subscribe to events in the PlayerVolume namespace for given player.

        Returns handle to unsubscribe.

        Reference:
        https://docs.sonos.com/reference/playervolume-subscribe-playerid
        """
        return await self._handle_subscribe(player_id, callback)

    async def unduck(
        self,
        player_id: str,
    ) -> None:
        """
        Send volume unduck command to player.

        Reference:
        https://docs.sonos.com/reference/playervolume-unduck-playerid
        """
        await self.api.send_command(
            namespace=self.namespace,
            command="unduck",
            playerId=player_id,
        )
