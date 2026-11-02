"""Handle PlaybackSession related endpoints for Sonos."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiosonos.api.models import SessionError, SessionInfo, SessionStatus, Track

from ._base import SonosNameSpace, SubscribeCallbackType, UnsubscribeCallbackType

if TYPE_CHECKING:
    from aiosonos.api.models import Container


class PlaybackSessionNameSpace(SonosNameSpace):
    """PlaybackSession Namespace handlers."""

    namespace = "playbackSession"
    event_type = "sessionInfo"
    error_event_type = "sessionError"
    _event_model = SessionInfo
    _event_key = "sessionId"

    async def create_session(
        self,
        group_id: str,
        app_id: str,
        app_context: str,
        account_id: str | None = None,
        custom_data: dict | None = None,
    ) -> SessionStatus:
        """
        Send createSession command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playbacksession-createsession-groupid
        """
        options = {
            "appId": app_id,
            "appContext": app_context,
        }
        if account_id is not None:
            options["accountId"] = account_id
        if custom_data is not None:
            options["customData"] = custom_data
        return await self.api.send_command(
            namespace=self.namespace,
            command="createSession",
            groupId=group_id,
            options=options,
        )

    async def load_cloud_queue(
        self,
        session_id: str,
        queue_base_url: str,
        http_authorization: str | None = None,
        use_http_authorization_for_media: bool | None = None,
        item_id: str | None = None,
        queue_version: str | None = None,
        position_millis: int | None = None,
        play_on_completion: bool | None = None,
        track_metadata: Track | None = None,
    ) -> None:
        """
        Send loadCloudQueue command to an (active) playback session).

        Reference:
        https://docs.sonos.com/reference/playbacksession-loadcloudqueue-sessionid
        """
        options = {
            "queueBaseUrl": queue_base_url,
        }
        if http_authorization is not None:
            options["httpAuthorization"] = http_authorization
        if use_http_authorization_for_media is not None:
            options["useHttpAuthorizationForMedia"] = use_http_authorization_for_media
        if item_id is not None:
            options["itemId"] = item_id
        if queue_version is not None:
            options["queueVersion"] = queue_version
        if position_millis is not None:
            options["positionMillis"] = position_millis
        if play_on_completion is not None:
            options["playOnCompletion"] = play_on_completion
        if track_metadata is not None:
            options["trackMetadata"] = track_metadata
        await self.api.send_command(
            namespace=self.namespace,
            command="loadCloudQueue",
            sessionId=session_id,
            options=options,
        )

    async def load_stream_url(
        self,
        session_id: str,
        stream_url: str,
        play_on_completion: bool | None = None,
        station_metadata: Container | None = None,
        item_id: str | None = None,
    ) -> None:
        """
        Send loadStreamUrl command to an (active) playback session).

        Reference:
        https://docs.sonos.com/reference/playbacksession-loadstreamurl-sessionid
        """
        options = {
            "streamUrl": stream_url,
        }
        if play_on_completion is not None:
            options["playOnCompletion"] = play_on_completion
        if station_metadata is not None:
            options["stationMetadata"] = station_metadata
        if item_id is not None:
            options["itemId"] = item_id
        await self.api.send_command(
            namespace=self.namespace,
            command="loadStreamUrl",
            sessionId=session_id,
            options=options,
        )

    async def refresh_cloud_queue(
        self,
        session_id: str,
    ) -> None:
        """
        Send refreshCloudQueue command to an (active) playback session).

        Reference:
        https://docs.sonos.com/reference/playbacksession-refreshcloudqueue-sessionid
        """
        await self.api.send_command(
            namespace=self.namespace,
            command="refreshCloudQueue",
            sessionId=session_id,
        )

    async def seek(
        self,
        session_id: str,
        position_millis: int,
        item_id: str | None = None,
    ) -> None:
        """
        Send seek command to an (active) playback session).

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playbacksession-seek-sessionid
        """
        options = {
            "positionMillis": position_millis,
        }
        if item_id is not None:
            options["itemId"] = item_id
        await self.api.send_command(
            namespace=self.namespace,
            command="seek",
            sessionId=session_id,
            options=options,
        )

    async def seek_relative(
        self,
        session_id: str,
        delta_millis: int,
        item_id: str | None = None,
    ) -> None:
        """
        Send seekRelative command to group.

        Note that when connected to a local speaker's websocket,
        the group id can only be that from the local speaker itself.

        Reference:
        https://docs.sonos.com/reference/playbacksession-seekrelative-sessionid
        """
        options = {
            "deltaMillis": delta_millis,
        }
        if item_id is not None:
            options["itemId"] = item_id
        await self.api.send_command(
            namespace=self.namespace,
            command="seekRelative",
            sessionId=session_id,
            options=options,
        )

    async def skip_to_item(
        self,
        session_id: str,
        item_id: str,
        queue_version: str | None = None,
        position_millis: int | None = None,
        play_on_completion: bool | None = None,
        track_metadata: Track | None = None,
    ) -> None:
        """
        Send skipToItem command to an (active) playback session).

        Reference:
        https://docs.sonos.com/reference/playbacksession-skiptoitem-sessionid
        """
        options = {
            "itemId": item_id,
        }
        if queue_version is not None:
            options["queueVersion"] = queue_version
        if position_millis is not None:
            options["positionMillis"] = position_millis
        if play_on_completion is not None:
            options["playOnCompletion"] = play_on_completion
        if track_metadata is not None:
            options["trackMetadata"] = track_metadata
        await self.api.send_command(
            namespace=self.namespace,
            command="skipToItem",
            sessionId=session_id,
            options=options,
        )

    async def suspend(
        self,
        session_id: str,
        queue_version: str | None = None,
    ) -> None:
        """
        Send suspend command to an (active) playback session).

        Reference:
        https://docs.sonos.com/reference/playbacksession-suspend-sessionid
        """
        options = {}
        if queue_version is not None:
            options["queueVersion"] = queue_version
        await self.api.send_command(
            namespace=self.namespace,
            command="suspend",
            sessionId=session_id,
            options=options,
        )

    async def leave_session(
        self,
        session_id: str,
        queue_version: str | None = None,
    ) -> None:
        """
        Send leaveSession command to a playback session: ends it, rather than suspending it.

        The session's playback stops at once and the player holds no session afterwards;
        subscribers of the session get a sessionError ERROR_SESSION_EVICTED. A command of
        the local API without a page on docs.sonos.com, verified on firmware 86.10 and 97.2.

        :param session_id: The session to leave.
        :param queue_version: The cloud queue version last loaded, if any.
        """
        options = {}
        if queue_version is not None:
            options["queueVersion"] = queue_version
        await self.api.send_command(
            namespace=self.namespace,
            command="leaveSession",
            sessionId=session_id,
            options=options,
        )

    async def subscribe(
        self,
        session_id: str,
        callback: SubscribeCallbackType[SessionInfo],
        error_callback: SubscribeCallbackType[SessionError] | None = None,
    ) -> UnsubscribeCallbackType:
        """
        Subscribe to events in the playbackSession namespace for a specific sessionId.

        :param session_id: The session to follow.
        :param callback: Receives sessionInfo events (session suspended or resumed).
        :param error_callback: Receives sessionError events, e.g.
            ERROR_SESSION_EVICTED when another app or source took over the group.
        :return: Handle that stops this call's listener (a no-op once used); the
            player's subscription is released when the last listener to the session stops.

        Reference:
        https://docs.sonos.com/reference/playbacksession-subscribe-sessionid
        """
        return await self._handle_subscribe(session_id, callback, error_callback)
