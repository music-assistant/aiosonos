"""
Representation of a Sonos Group.

Sonos players are always in groups, even if the group has only one player.
All players in a group play the same audio in synchrony.
Users can easily move players from one group to another without interrupting playback.
Transport controls, such as play, pause, skip to next track, and skip to previous track,
target groups rather than individual players.
Players must be part of the same household to be part of a group.

Reference: https://docs.sonos.com/docs/control
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from functools import partial
from typing import TYPE_CHECKING

from aiosonos.api.models import ContainerType, MetadataStatus, MusicService, PlayBackState
from aiosonos.api.models import GroupVolume as GroupVolumeData
from aiosonos.api.models import PlaybackStatus as PlaybackStatusData
from aiosonos.api.models import PlayModes as PlayModesData
from aiosonos.const import EventType, GroupEvent, PlaybackErrorEvent, SessionErrorEvent
from aiosonos.exceptions import CommandTimeout, FailedCommand, InvalidState

from .api.models import PlaybackActions as PlaybackActionsData

if TYPE_CHECKING:
    from collections.abc import Callable

    from aiosonos.api.models import (
        Container,
        PlaybackError,
        SessionError,
        SessionInfo,
        SessionStatus,
        Track,
    )

    from .api.models import Group as GroupData
    from .client import SonosLocalApiClient

_LOGGER = logging.getLogger(__name__)

SESSION_EVICTED_ERROR = "ERROR_SESSION_EVICTED"
DEFAULT_APP_ID = "com.aiosonos.playback"
DEFAULT_APP_CONTEXT = "1"


def _session_error(err: FailedCommand) -> SessionError:
    """Return the sessionError event a command reply with a session error code stands for."""
    error: SessionError = {"_objectType": "sessionError", "errorCode": err.error_code}
    if err.details:
        error["reason"] = err.details
    return error


class SonosGroup:
    """Representation of a Sonos Group."""

    def __init__(self, client: SonosLocalApiClient, data: GroupData) -> None:
        """Handle initialization."""
        self.client = client
        self.active_session_id: str | None = None
        self._data = data
        # to prevent race conditions at startup/init,
        # we set some default values for the status dicts here
        self._play_modes = PlayModes({})
        self._volume_data = GroupVolumeData(
            objectType="groupVolume", fixed=False, volume=0, muted=False
        )
        playback_actions = PlaybackActionsData(
            canCrossfade=False,
            canPause=False,
            canPlay=False,
            canSeek=False,
            canSkip=False,
            canSkipToPrevious=False,
            canStop=False,
        )
        self._playback_actions = PlaybackActions(playback_actions)
        self._playback_status_data: PlaybackStatusData = PlaybackStatusData(
            objectType="playbackStatus",
            availablePlaybackActions=playback_actions,
            isDucking=False,
            playbackState=PlayBackState.PLAYBACK_STATE_IDLE,
            playModes=PlayModesData(),
            positionMillis=0,
            previousPositionMillis=0,
        )
        self._playback_metadata_data: MetadataStatus = MetadataStatus(objectType="metadataStatus")
        self._playback_status_last_updated: float = 0.0
        self._unsubscribe_callbacks = []
        # the session listened to for sessionInfo/sessionError events; kept until another
        # session takes its place or the group is cleaned up, as a stopped session may be
        # handed back by the next createSession
        self._subscribed_session_id: str | None = None
        self._unsubscribe_session: Callable[[], None] | None = None
        # the session evicted since the last creation started: handed back by that
        # creation, or subscribed to by it, it is refused; one evicted earlier is not
        self._evicted_session_id: str | None = None
        # how often the active session was evicted; a stop ordered before an eviction
        # that finds no session afterwards is complete
        self._evictions = 0
        # advanced by cleanup, so a session subscription that completes after it
        # is undone instead of installed
        self._cleanup_generation = 0
        # one creation at a time, through to its subscription and the load that follows,
        # so two never subscribe to one session twice or load into a session that is
        # still being subscribed to
        self._session_lock = asyncio.Lock()

    def cleanup(self) -> None:
        """Handle cleanup on deletion, a move to another coordinator or a new connection."""
        self._unsubscribe_status()
        self._cleanup_generation += 1
        self._stop_session_listener()
        # no session is vouched for without listening to it; the next play makes a new one
        self.active_session_id = None

    @property
    def is_subscribed(self) -> bool:
        """Return whether this group's event subscriptions are in place.

        Without them the playback, volume and metadata status never update.
        """
        return bool(self._unsubscribe_callbacks)

    @property
    def coordinated_by_client(self) -> bool:
        """Return whether the connected player is this group's coordinator.

        A player's local websocket only serves the group that player
        coordinates; any other group is remote and cannot be subscribed to.
        """
        return self.coordinator_id == self.client.player_id

    async def async_init(self) -> None:
        """Handle Async initialization.

        Reads the group's status and subscribes to its updates. A remote group
        (one the connected player does not coordinate) is left without status
        and subscriptions and no command is sent for it: the player refuses
        them with ``groupCoordinatorChanged``, as its coordinator's connection
        is the one that tracks it. The same refusal for a group this player
        coordinates is transient (the player is still settling into the role),
        so it is raised like any other failure for the caller to retry;
        whatever was subscribed before the failure is undone.
        """
        if not self.coordinated_by_client:
            self.cleanup()
            self._clear_status()
            return
        # grab playback data and setup subscription
        try:
            self._volume_data = await self.client.api.group_volume.get_volume(self.id)
            self._playback_status_data = await self.client.api.playback.get_playback_status(self.id)
            self._playback_status_last_updated = time.time()
            self._playback_actions = PlaybackActions(
                self._playback_status_data["availablePlaybackActions"],
            )
            self._play_modes = PlayModes(self._playback_status_data["playModes"])
            self._playback_metadata_data = (
                await self.client.api.playback_metadata.get_metadata_status(
                    self.id,
                )
            )
            # one at a time, so a failure part-way can undo what succeeded
            self._unsubscribe_callbacks.append(
                await self.client.api.playback.subscribe(
                    self.id,
                    self._handle_playback_status_update,
                    self._handle_playback_error,
                ),
            )
            self._unsubscribe_callbacks.append(
                await self.client.api.group_volume.subscribe(
                    self.id,
                    self._handle_volume_update,
                ),
            )
            self._unsubscribe_callbacks.append(
                await self.client.api.playback_metadata.subscribe(
                    self.id,
                    self._handle_metadata_status_update,
                ),
            )
        except FailedCommand as err:
            # the playback session, if any, is listened to apart from the status: a
            # failure here (retried by the caller) must not stop that
            self._unsubscribe_status()
            self._clear_status()
            if err.error_code == "groupCoordinatorChanged" and not self.coordinated_by_client:
                # retrieving group details is not possible for remote groups when
                # connected to a player's local websocket.
                self.cleanup()
                return
            _LOGGER.debug("Setup of group %s failed: %s", self.id, err)
            raise
        except Exception:
            # a dropped connection, a timeout: undo any status subscription made so far
            self._unsubscribe_status()
            raise

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
        return (
            self._playback_status_data.get("playbackState")
            or self._data.get("playbackState")
            or PlayBackState.PLAYBACK_STATE_IDLE
        )

    @property
    def player_ids(self) -> list[str]:
        """Return the id's of this group's members."""
        return self._data["playerIds"]

    @property
    def area_ids(self) -> list[str]:
        """Return the area id's of this group (if any)."""
        return self._data.get("areaIds", [])

    @property
    def playback_actions(self) -> PlaybackActions:
        """Return the playback actions of this group."""
        return self._playback_actions

    @property
    def playback_metadata(self) -> MetadataStatus:
        """Return the MetadataStatus of this group."""
        return self._playback_metadata_data

    @property
    def position(self) -> float:
        """Return the (corrected) current position in (fractions of) seconds."""
        if self.playback_state == PlayBackState.PLAYBACK_STATE_PLAYING:
            return self._playback_status_data.get("positionMillis", 0) / 1000 + (
                time.time() - self._playback_status_last_updated
            )
        return self._playback_status_data.get("positionMillis", 0) / 1000

    @property
    def is_ducking(self) -> bool:
        """Return if the group's volume is currently ducked."""
        return self._playback_status_data.get("isDucking", False)

    @property
    def play_modes(self) -> PlayModes:
        """Return the play modes of this group."""
        return self._play_modes

    @property
    def container_type(self) -> ContainerType | None:
        """Return the container_type of the active source of this group (if any)."""
        if not (container := self._playback_metadata_data.get("container")):
            return None
        if container_type := container.get("type"):
            if container_type in ContainerType:
                return ContainerType(container_type)
            # return the raw string value if it's not a known container type
            return container_type
        return None

    @property
    def active_service(self) -> MusicService | None:
        """Return the active service of the active source of this group (if any)."""
        if not (container := self._playback_metadata_data.get("container")):
            return None
        if (container_id := container.get("id")) and (service_id := container_id.get("serviceId")):
            if service_id in MusicService:
                return MusicService(service_id)
            # return the raw string value if it's not a known container type
            return service_id
        return None

    async def play(self) -> None:
        """Send play command to group."""
        await self.client.api.playback.play(self.id)

    async def pause(self) -> None:
        """Send pause command to group."""
        await self.client.api.playback.pause(self.id)

    async def stop(self) -> None:
        """
        Send stop command to group; a stop ordered during a play lands after it.

        A session evicted meanwhile counts as stopped, and nothing else is loaded, so the
        group is not taken back from whatever took it over. Raises `CommandTimeout` when the
        player does not answer, `InvalidState` when the group is cleaned up while the clear
        session is made.
        """
        # a play under the lock may give this stop its session yet; evicted before the
        # stop gets its turn, that session counts as stopped as well
        evictions = self._evictions
        async with self._session_lock:
            generation = self._cleanup_generation
            session_id = self.active_session_id
            if session_id is None and self._evictions != evictions:
                return
            try:
                # always first attempt to suspend the active session
                await self.client.api.playback_session.suspend(session_id)
            except CommandTimeout:
                # the player may have suspended already; do not clear its queue
                raise
            except FailedCommand as err:
                if session_id is not None and err.error_code == SESSION_EVICTED_ERROR:
                    # the reply says what a sessionError event would: handled as one
                    self._handle_session_error(generation, session_id, _session_error(err))
                if session_id is not None and session_id == self._evicted_session_id:
                    # another app or source took the group over meanwhile: the session is
                    # stopped, and the clear below would take the group back from it
                    return
                # this turns out the best way to clear the queue,
                # just send an invalid uri and it will clear the queue
                # and stop any playing content, including linein sources
                # (the session is over either way: its eviction by the clear is no takeover)
                self.active_session_id = None
                try:
                    await self._play_stream_url("clear", None)
                except CommandTimeout:
                    # unanswered as well: the caller must not take the stop for done
                    raise
                except FailedCommand:
                    pass
            finally:
                self.active_session_id = None

    async def toggle_play_pause(self) -> None:
        """Send play/pause command to group."""
        await self.client.api.playback.toggle_play_pause(self.id)

    async def skip_to_next_track(self) -> None:
        """Send skipToNextTrack command to group."""
        await self.client.api.playback.skip_to_next_track(self.id)

    async def skip_to_previous_track(self) -> None:
        """Send skipToPreviousTrack command to group."""
        await self.client.api.playback.skip_to_previous_track(self.id)

    async def set_play_modes(
        self,
        crossfade: bool | None = None,
        repeat: bool | None = None,
        repeat_one: bool | None = None,
        shuffle: bool | None = None,
    ) -> None:
        """Send setPlayModes command to group."""
        await self.client.api.playback.set_play_modes(
            self.id,
            crossfade=crossfade,
            repeat=repeat,
            repeat_one=repeat_one,
            shuffle=shuffle,
        )

    async def seek(self, position: int) -> None:
        """Send seek command to group."""
        await self.client.api.playback.seek(self.id, position)

    async def seek_relative(self, delta: int) -> None:
        """Send seekRelative command to group."""
        await self.client.api.playback.seek_relative(self.id, delta)

    async def load_line_in(
        self,
        device_id: str | None = None,
        play_on_completion: bool = False,  # noqa: FBT002
    ) -> None:
        """
        Send loadLineIn command to group.

        Parameters:
        - device_id (Optional): Represents the line-in source,
        any player in the household that supports line-in.
        The default value is the local deviceId.
        This is the same as the player ID returned in the player object.

        - play_on_completion (Optional): If true, start playback after
        loading the line-in source. If false, the player loads the cloud queue,
        but requires the play command to begin.
        If not provided, the default value is false.
        """
        await self.client.api.playback.load_line_in(
            self.id,
            device_id=device_id,
            play_on_completion=play_on_completion,
        )

    async def modify_group_members(
        self,
        player_ids_to_add: list[str],
        player_ids_to_remove: list[str],
    ) -> None:
        """Modify the group's members."""
        await self.client.api.groups.modify_group_members(
            self.id,
            player_ids_to_add,
            player_ids_to_remove,
        )

    async def set_group_members(
        self,
        player_ids: list[str],
        area_ids: list[str] | None = None,
    ) -> None:
        """Set/replace the group's members."""
        await self.client.api.groups.set_group_members(self.id, player_ids, area_ids)

    async def create_playback_session(
        self,
        app_id: str = DEFAULT_APP_ID,
        app_context: str = DEFAULT_APP_CONTEXT,
        account_id: str | None = None,
        custom_data: dict | None = None,
    ) -> SessionStatus:
        """
        Create a new Playback Session.

        The session is subscribed to, so an eviction (another app or source took
        over the group) clears active_session_id and is signalled as a
        SESSION_ERROR event with the session's id; so is an eviction of the
        previous session while this one is created. A refused subscription does
        not fail the session.

        Raises FailedCommand (ERROR_SESSION_EVICTED) when the session was evicted,
        and InvalidState when the group was cleaned up, before this returns: the
        session is not handed out to play on in either case.

        :param app_id: The app the session is created for.
        :param app_context: The app's own context, to find the session again.
        :param account_id: The account on the app's service, if any.
        :param custom_data: Data to keep with the session.
        """
        async with self._session_lock:
            return await self._create_playback_session(app_id, app_context, account_id, custom_data)

    async def play_stream_url(self, url: str, metadata: Container) -> None:
        """Create a new playback session and start playing a single (radio) stream URL."""
        async with self._session_lock:
            await self._play_stream_url(url, metadata)

    async def play_cloud_queue(
        self,
        queue_base_url: str,
        http_authorization: str | None = None,
        use_http_authorization_for_media: bool | None = None,
        item_id: str | None = None,
        queue_version: str | None = None,
        position_millis: int | None = None,
        track_metadata: Track | None = None,
    ) -> None:
        """
        Start playing a (cloud) queue in the active playback session, or a new one.

        Queues started together load one after the other, in order.

        For all options, see:
        https://docs.sonos.com/reference/playbacksession-loadcloudqueue-sessionid
        """
        async with self._session_lock:
            session_id = self.active_session_id
            if not session_id:
                session = await self._create_playback_session(
                    DEFAULT_APP_ID, DEFAULT_APP_CONTEXT, None, None
                )
                session_id = session["sessionId"]
            generation = self._cleanup_generation
            try:
                await self.client.api.playback_session.load_cloud_queue(
                    session_id,
                    queue_base_url=queue_base_url,
                    http_authorization=http_authorization,
                    use_http_authorization_for_media=use_http_authorization_for_media,
                    item_id=item_id,
                    queue_version=queue_version,
                    position_millis=position_millis,
                    play_on_completion=True,
                    track_metadata=track_metadata,
                )
            except FailedCommand as err:
                self._handle_refused_load(generation, session_id, err)
                raise

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

    def _unsubscribe_status(self) -> None:
        """Stop the playback, volume and metadata status subscriptions (if any)."""
        for unsubscribe_callback in self._unsubscribe_callbacks:
            # On a closed connection the unsubscribe wire-command raises
            # InvalidState, but the namespace listener is already removed by
            # then, so swallow it and keep tearing down the remaining listeners.
            with suppress(InvalidState):
                unsubscribe_callback()
        self._unsubscribe_callbacks = []

    def _clear_status(self) -> None:
        """Drop the group's status, for a group this player cannot read it from."""
        self._volume_data = {}
        self._playback_status_data = {}
        self._playback_actions = PlaybackActions({})
        self._play_modes = PlayModes({})
        self._playback_metadata_data = {}

    def _handle_playback_status_update(self, data: PlaybackStatusData) -> None:
        """Handle playbackStatus update."""
        # the position is extrapolated from this moment on, also when nothing else changed
        self._playback_status_last_updated = time.time()
        if data == self._playback_status_data:
            return
        self._playback_status_data = data
        self._playback_actions.raw_data.update(data["availablePlaybackActions"])
        self._play_modes.raw_data.update(data["playModes"])
        self.client.signal_event(
            GroupEvent(
                EventType.GROUP_UPDATED,
                self.id,
                self,
            ),
        )

    def _handle_metadata_status_update(self, data: MetadataStatus) -> None:
        """Handle MetadataStatus update."""
        if data == self._playback_metadata_data:
            return
        self._playback_metadata_data = data
        self.client.signal_event(
            GroupEvent(
                EventType.GROUP_UPDATED,
                self.id,
                self,
            ),
        )

    def _handle_volume_update(self, data: GroupVolumeData) -> None:
        """Handle volume update."""
        if data == self._volume_data:
            return
        self._volume_data = data
        self.client.signal_event(
            GroupEvent(
                EventType.GROUP_UPDATED,
                self.id,
                self,
            ),
        )

    def _handle_playback_error(self, data: PlaybackError) -> None:
        """Handle playbackError event."""
        self.client.signal_event(
            PlaybackErrorEvent(
                EventType.PLAYBACK_ERROR,
                self.id,
                data,
            ),
        )

    async def _create_playback_session(
        self,
        app_id: str,
        app_context: str,
        account_id: str | None,
        custom_data: dict | None,
    ) -> SessionStatus:
        """Create and subscribe to a session; the caller holds _session_lock."""
        generation = self._cleanup_generation
        # an eviction from here on is one that happened while the session was made; an
        # earlier one does not count against a session the speaker hands back again
        self._evicted_session_id = None
        session = await self.client.api.playback_session.create_session(
            self.id,
            app_id,
            app_context,
            account_id,
            custom_data,
        )
        session_id = session["sessionId"]
        if session_id == self._evicted_session_id:
            # the speaker handed back a session evicted meanwhile: the event handled it
            # (signalled when it was the active one), it is not handed out to play on
            msg = f"Session {session_id} was evicted while it was created"
            raise FailedCommand(SESSION_EVICTED_ERROR, msg)
        if generation != self._cleanup_generation:
            msg = f"Group {self.id} was cleaned up while session {session_id} was created"
            raise InvalidState(msg)
        self.active_session_id = session_id
        if self._subscribed_session_id == session_id:
            # listened to already: in use, or stopped and handed back again
            return session
        # the listener of another session (replaced, or stopped earlier) makes way
        self._stop_session_listener()
        unsubscribe: Callable[[], None] | None = None
        try:
            unsubscribe = await self.client.api.playback_session.subscribe(
                session_id,
                self._handle_session_info,
                partial(self._handle_session_error, generation, session_id),
            )
        except CommandTimeout as err:
            # the session is used without a listener (the namespace unsubscribes in
            # case the speaker holds the subscription anyway)
            _LOGGER.warning("No reply subscribing to session %s: %s", session_id, err)
        except FailedCommand as err:
            if err.error_code == SESSION_EVICTED_ERROR:
                # the reply says what a sessionError event would: handled as one, and the
                # check below ends the session
                self._handle_session_error(generation, session_id, _session_error(err))
            else:
                _LOGGER.debug("Could not subscribe to session %s: %s", session_id, err)
        except BaseException:
            # cut short (cancelled, or the connection gone): nobody listens to the
            # session, so it is not vouched for; the next play makes a new one
            self.active_session_id = None
            raise
        if generation != self._cleanup_generation or session_id == self._evicted_session_id:
            # the group was cleaned up, or the session evicted, in the meantime: the
            # subscription (if made) is undone and the session not handed out
            if unsubscribe is not None:
                with suppress(InvalidState):
                    unsubscribe()
            if session_id == self._evicted_session_id:
                msg = f"Session {session_id} was evicted while it was subscribed to"
                raise FailedCommand(SESSION_EVICTED_ERROR, msg)
            msg = f"Group {self.id} was cleaned up while session {session_id} was subscribed to"
            raise InvalidState(msg)
        if unsubscribe is None:
            # a refused subscription does not fail the session
            return session
        self._subscribed_session_id = session_id
        self._unsubscribe_session = unsubscribe
        return session

    async def _play_stream_url(self, url: str, metadata: Container) -> None:
        """Create a session and load a stream URL into it; the caller holds _session_lock."""
        session = await self._create_playback_session(
            DEFAULT_APP_ID, DEFAULT_APP_CONTEXT, None, None
        )
        generation = self._cleanup_generation
        try:
            await self.client.api.playback_session.load_stream_url(
                session["sessionId"],
                stream_url=url,
                play_on_completion=True,
                station_metadata=metadata,
            )
        except FailedCommand as err:
            self._handle_refused_load(generation, session["sessionId"], err)
            raise

    def _handle_refused_load(self, generation: int, session_id: str, err: FailedCommand) -> None:
        """
        Settle a load the player refused: the session is not played into again.

        An eviction in the reply counts like the sessionError event; any other refusal
        (not an unanswered load, which may have gone through) ends the session's use,
        so the next play makes a new one.
        """
        if isinstance(err, CommandTimeout):
            return
        if err.error_code == SESSION_EVICTED_ERROR:
            self._handle_session_error(generation, session_id, _session_error(err))
        else:
            self.active_session_id = None

    def _stop_session_listener(self) -> None:
        """Stop listening to the session subscribed to (if any)."""
        if self._unsubscribe_session is None:
            return
        unsubscribe, self._unsubscribe_session = self._unsubscribe_session, None
        self._subscribed_session_id = None
        with suppress(InvalidState):
            unsubscribe()

    def _handle_session_info(self, data: SessionInfo) -> None:
        """Handle sessionInfo event (session suspended or resumed)."""
        _LOGGER.debug("Session info for group %s: %s", self.id, data)

    def _handle_session_error(self, generation: int, session_id: str, data: SessionError) -> None:
        """
        Handle sessionError event, e.g. an eviction by another app or source.

        :param generation: The cleanup generation the session was subscribed to under.
        :param session_id: The session the error is about.
        :param data: The event body.
        """
        if generation != self._cleanup_generation:
            # subscribed before the group was cleaned up: no longer its concern
            return
        evicted = data.get("errorCode") == SESSION_EVICTED_ERROR
        if evicted:
            self._evicted_session_id = session_id
            if session_id == self._subscribed_session_id:
                # gone for good: nothing left to listen to
                self._stop_session_listener()
        if session_id != self.active_session_id:
            # a session this group already replaced or stopped
            _LOGGER.debug("Error for inactive session %s: %s", session_id, data)
            return
        if evicted:
            # the group is no longer under this session's control
            self.active_session_id = None
            self._evictions += 1
        self.client.signal_event(
            SessionErrorEvent(
                EventType.SESSION_ERROR,
                self.id,
                {**data, "sessionId": session_id},
            ),
        )


class PlaybackActions:
    """Representation of the PlaybackActions on a Sonos Group."""

    def __init__(self, raw_data: PlaybackActionsData) -> None:
        """Handle initialization."""
        self.raw_data = raw_data

    @property
    def can_skip(self) -> bool:
        """Return if the group can skip to the next item."""
        return self.raw_data.get("canSkip", False)

    @property
    def can_skip_to_previous(self) -> bool:
        """Return if the group can skip to the previous item."""
        # canSkipBack is the pre-1.36.0 name of canSkipToPrevious
        return self.raw_data.get("canSkipToPrevious", self.raw_data.get("canSkipBack", False))

    @property
    def can_skip_forward(self) -> bool:
        """Return if the group can skip forward (alias of can_skip)."""
        return self.can_skip

    @property
    def can_skip_backward(self) -> bool:
        """Return if the group can skip backward (alias of can_skip_to_previous)."""
        return self.can_skip_to_previous

    @property
    def can_play(self) -> bool:
        """Return if the group can play."""
        return self.raw_data.get("canPlay", False)

    @property
    def can_pause(self) -> bool:
        """Return if the group can pause."""
        return self.raw_data.get("canPause", False)

    @property
    def can_stop(self) -> bool:
        """Return if the group can stop."""
        return self.raw_data.get("canStop", False)


class PlayModes:
    """Representation of the PlayModes on a Sonos Group."""

    def __init__(self, raw_data: PlayModesData) -> None:
        """Handle initialization."""
        self.raw_data = raw_data

    @property
    def crossfade(self) -> bool | None:
        """Return if crossfade is enabled."""
        return self.raw_data.get("crossfade")

    @property
    def repeat(self) -> bool | None:
        """Return if repeat is enabled."""
        return self.raw_data.get("repeat")

    @property
    def repeat_one(self) -> bool | None:
        """Return if repeat one is enabled."""
        return self.raw_data.get("repeatOne")

    @property
    def shuffle(self) -> bool | None:
        """Return if shuffle is enabled."""
        return self.raw_data.get("shuffle")
