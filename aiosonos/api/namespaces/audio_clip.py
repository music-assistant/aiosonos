"""Handle AudioClip related endpoints for Sonos."""

from __future__ import annotations

from aiosonos.api.models import (
    AudioClip,
    AudioClipLEDBehavior,
    AudioClipPriority,
    AudioClipStatusEvent,
    AudioClipType,
)

from ._base import SonosNameSpace, SubscribeCallbackType, UnsubscribeCallbackType


class AudioClipNameSpace(SonosNameSpace):
    """AudioClip Namespace handlers."""

    namespace = "audioClip"
    event_type = "audioClip"
    _event_model = AudioClipStatusEvent
    _event_key = "playerId"

    async def load_audio_clip(
        self,
        player_id: str,
        name: str,
        app_id: str,
        stream_url: str | None = None,
        volume: int | None = None,
        priority: AudioClipPriority = AudioClipPriority.LOW,
        clip_type: AudioClipType = AudioClipType.CHIME,
        http_authorization: str | None = None,
        clip_led_behavior: AudioClipLEDBehavior = AudioClipLEDBehavior.NONE,
    ) -> AudioClip:
        """
        Send loadAudioClip command to player.

        Note that when connected to a local speaker's websocket,
        the player id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/audioclip-loadaudioclip-playerid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="loadAudioClip",
            playerId=player_id,
            options={
                "name": name,
                "appId": app_id,
                "priority": priority,
                "clipType": clip_type,
                "streamUrl": stream_url,
                "httpAuthorization": http_authorization,
                "volume": volume,
                "clipLEDBehavior": clip_led_behavior,
            },
        )

    async def subscribe(
        self,
        player_id: str,
        callback: SubscribeCallbackType,
    ) -> UnsubscribeCallbackType:
        """
        Subscribe to events in the AudioClip namespace for given player.

        Returns handle to unsubscribe.

        Reference:
        https://docs.sonos.com/reference/audioclip-subscribe-playerid
        """
        return await self._handle_subscribe(player_id, callback)
