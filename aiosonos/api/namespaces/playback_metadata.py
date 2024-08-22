"""Handle PlaybackMetadata related endpoints for Sonos."""

from __future__ import annotations

from aiosonos.api.models import MetadataStatus

from ._base import SonosNameSpace, SubscribeCallbackType, UnsubscribeCallbackType


class PlaybackMetadataNameSpace(SonosNameSpace):
    """PlaybackMetadataNameSpace Namespace handlers."""

    namespace = "playbackMetadata"
    event_type = "metadataStatus"
    _event_model = MetadataStatus
    _event_key = "groupId"

    async def get_metadata_status(
        self,
        group_id: str,
    ) -> MetadataStatus:
        """
        Send getMetadataStatus command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playbackmetadata-getmetadatastatus-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="getMetadataStatus",
            groupId=group_id,
        )

    async def subscribe(
        self,
        group_id: str,
        callback: SubscribeCallbackType,
    ) -> UnsubscribeCallbackType:
        """
        Subscribe to events in the MetadataStatus namespace for given player.

        Returns handle to unsubscribe.

        Reference:
        https://docs.sonos.com/reference/playback-subscribe-groupid
        """
        return await self._handle_subscribe(group_id, callback)
