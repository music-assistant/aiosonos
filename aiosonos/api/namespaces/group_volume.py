"""Handle GroupVolume related endpoints for Sonos."""

from __future__ import annotations

from aiosonos.api.models import GroupVolume

from ._base import SonosNameSpace, SubscribeCallbackType, UnsubscribeCallbackType


class GroupVolumeNameSpace(SonosNameSpace):
    """GroupVolume Namespace handlers."""

    namespace = "groupVolume"
    event_type = "groupVolume"
    _event_model = GroupVolume
    _event_key = "groupId"

    async def set_volume(
        self,
        group_id: str,
        volume: int,
    ) -> None:
        """
        Send setVolume command to set the group's volume.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/groupvolume-setvolume-groupid
        """
        await self.api.send_command(
            namespace=self.namespace,
            command="setVolume",
            groupId=group_id,
            options={"volume": volume},
        )

    async def get_volume(
        self,
        group_id: str,
    ) -> GroupVolume:
        """
        Get the group's volume and mute state.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/groupvolume-getvolume-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="getVolume",
            groupId=group_id,
        )

    async def set_mute(
        self,
        group_id: str,
        muted: bool,  # noqa: FBT001
    ) -> None:
        """
        Send the setMute command to set the group's mute state.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/groupvolume-setmute-groupid
        """
        await self.api.send_command(
            namespace=self.namespace,
            command="setMute",
            groupId=group_id,
            options={"muted": muted},
        )

    async def set_relative_volume(
        self,
        group_id: str,
        volume_delta: int | None = None,
    ) -> None:
        """
        Send setRelativeVolume command to relatively change the group volume.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/groupvolume-setrelativevolume-groupid
        """
        await self.api.send_command(
            namespace=self.namespace,
            command="setRelativeVolume",
            groupId=group_id,
            options={"volumeDelta": volume_delta},
        )

    async def subscribe(
        self,
        group_id: str,
        callback: SubscribeCallbackType,
    ) -> UnsubscribeCallbackType:
        """
        Subscribe to events in the GroupVolume namespace for given group.

        Returns handle to unsubscribe.

        Reference:
        https://docs.sonos.com/reference/groupvolume-subscribe-groupid
        """
        return await self._handle_subscribe(group_id, callback)
