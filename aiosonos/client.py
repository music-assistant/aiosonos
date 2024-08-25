"""
Sonos API Client to manage a single Sonos speaker, using the local websockets api.

Although the only connection method that is implemented,
is the local websockets connection, the cloud API shares the same models and
namespaces so this client could be extended to support the cloud API as well.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Self

from aiosonos.const import EventType, GroupEvent, SonosEvent
from aiosonos.utils import get_discovery_info

from .api.websockets import SonosLocalWebSocketsApi
from .group import SonosGroup
from .player import SonosPlayer

if TYPE_CHECKING:
    from types import TracebackType

    from aiohttp import ClientSession

    from aiosonos.api.models import GroupInfo

    from .api.models import Group as GroupData
    from .api.models import Groups as GroupsData


EventCallBackType = Callable[[SonosEvent], None]
EventSubscriptionType = tuple[
    EventCallBackType,
    tuple[EventType, ...] | None,
    tuple[str, ...] | None,
]


class SonosLocalApiClient:
    """Sonos API Client to manage a single Sonos speaker, using the local websockets api."""

    api: SonosLocalWebSocketsApi
    _loop = asyncio.BaseEventLoop
    _household_id: str = ""
    _player_id: str
    _player: SonosPlayer | None = None

    def __init__(self, player_ip: str, aiohttp_session: ClientSession) -> None:
        """Initialize the Sonos API client."""
        self.player_ip = player_ip
        self._aiohttp_session = aiohttp_session
        self._groups: dict[str, SonosGroup] = {}
        self._subscribers: list[EventSubscriptionType] = []

    @property
    def player_id(self) -> str:
        """Return the player id."""
        return self._player_id

    @property
    def player(self) -> SonosPlayer:
        """Return the player."""
        return self._player

    @property
    def household_id(self) -> str:
        """Return the household id."""
        return self._household_id

    @property
    def groups(self) -> list[SonosGroup]:
        """Return all groups available in the Sonos household."""
        return list(self._groups.values())

    def get_group(self, group_id: str) -> SonosGroup:
        """Return a group."""
        return self._groups[group_id]

    def subscribe(
        self,
        cb_func: EventSubscriptionType,
        event_filter: EventType | tuple[EventType] | None = None,
        object_id_filter: str | tuple[str] | None = None,
    ) -> Callable[[], None]:
        """Add callback to event listeners.

        Returns function to remove the listener.

        Parameters:
            - cb_func: callback function or coroutine
            - event_filter: Optionally only listen for these events
            - object_id_filter: Optionally only listen for these id's (player id, etc.)
        """
        if isinstance(event_filter, EventType):
            event_filter = (event_filter,)
        if isinstance(object_id_filter, str):
            object_id_filter = (object_id_filter,)
        listener = (cb_func, event_filter, object_id_filter)
        self._subscribers.append(listener)

        def remove_listener() -> None:
            self._subscribers.remove(listener)

        return remove_listener

    def signal_event(self, event: SonosEvent) -> None:
        """Forward event to subscribers."""
        for cb_func, event_filter, id_filter in self._subscribers:
            if not (event_filter is None or event.event_type in event_filter):
                continue
            if not (id_filter is None or event.object_id in id_filter):
                continue
            self._loop.call_soon_threadsafe(cb_func, event)

    async def connect(self) -> None:
        """Connect to the API."""
        self._loop = asyncio.get_running_loop()
        # retrieve discovery details from player first
        discovery_info = await get_discovery_info(self._aiohttp_session, self.player_ip)
        self._player_id = discovery_info["playerId"]
        self._household_id = discovery_info["householdId"]
        # Connect to the local websocket API
        self.api = SonosLocalWebSocketsApi(
            discovery_info["websocketUrl"],
            self._aiohttp_session,
        )
        # NOTE: connect will raise when connecting failed
        await self.api.connect()

    async def disconnect(self) -> None:
        """Disconnect the client and cleanup."""
        await self.api.disconnect()

    async def start_listening(self, init_ready: asyncio.Event | None = None) -> None:
        """Fetch initial state keep listening to messages until stopped."""
        listen_task = asyncio.create_task(self.api.start_listening())
        # fetch all initial data and setup subscriptions
        groups_data = await self.api.groups.get_groups(
            self.household_id,
            include_device_info=True,
        )
        for group_data in groups_data["groups"]:
            await self._setup_group(group_data)
        # Although all players are returned in the groups data,
        # the local api can only process the player that it is connected to
        # so we ignore all other player objects. For each Sonos player,
        # an individual api connection should be set-up to manage the player.
        # The Cloud API however is able to manage all players in the household.
        player_data = next(x for x in groups_data["players"] if x["id"] == self._player_id)
        self._player = player = SonosPlayer(self, player_data)
        await player.async_init()
        # setup global groups/player subscription
        await self.api.groups.subscribe(self._household_id, self._handle_groups_event)
        # set event that initial setup is done
        init_ready.set()
        # wait (forever) for incoming messages
        await listen_task

    async def create_group(
        self,
        player_ids: list[str],
        music_context_group_id: str | None = None,
    ) -> GroupInfo:
        """
        Create a new group.

        Use the createGroup command in the groups namespace to
        create a new group from a list of players. The player returns
        a group object with the group ID. This may be an existing
        group ID if an existing group is a subset of the new group.
        In this case, Sonos may build the new group by adding new
        players to the existing group.

        musicContextGroupId (Optional): The group containing the audio
        that you want to use. If empty or not provided,
        the new group will not contain any audio.
        """
        await self.api.groups.create_group(
            self._household_id,
            player_ids,
            music_context_group_id,
        )

    def _handle_groups_event(self, groups_data: GroupsData) -> None:
        """Handle a groups event."""
        # handle group updates
        for group_data in groups_data["groups"]:
            if group_data["id"] in self._groups:
                # existing group object
                self._groups[group_data["id"]].update_data(group_data)
                continue
            # a new group was added
            self._loop.create_task(self._setup_group(group_data))
        # check if any groups are removed
        removed_groups = set(self._groups.keys()) - {g["id"] for g in groups_data["groups"]}
        for group_id in removed_groups:
            group = self._groups.pop(group_id)
            self.signal_event(
                GroupEvent(
                    EventType.GROUP_REMOVED,
                    group_id,
                    group,
                ),
            )
        # handle player updates
        for player_data in groups_data["players"]:
            if player_data["id"] != self._player_id:
                continue
            self._player.update_data(player_data)

    async def _setup_group(self, group_data: GroupData) -> None:
        """Register/setup a (new) group."""
        group = SonosGroup(self, group_data)
        self._groups[group.id] = group
        await group.async_init()
        # always let the player check if the group changed,
        # as this might have been the active group
        if self._player:
            self._player.check_active_group()
        self.signal_event(
            GroupEvent(
                EventType.GROUP_ADDED,
                group.id,
                group,
            ),
        )

    async def __aenter__(self) -> Self:
        """Initialize and connect."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """Exit and disconnect."""
        await self.disconnect()
