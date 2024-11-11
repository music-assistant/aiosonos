"""Constants/Models for the SonosApiClient."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .group import SonosGroup
    from .player import SonosPlayer

CLOUD_BASE_URL = "api.ws.sonos.com/control/api/v1"
LOCAL_API_TOKEN = "123e4567-e89b-12d3-a456-426655440000"  # noqa: S105
LOG_LEVEL_VERBOSE = 5


class EventType(StrEnum):
    """Event types for the Sonos Client."""

    GROUP_ADDED = "group_added"
    GROUP_UPDATED = "group_updated"
    GROUP_REMOVED = "group_removed"
    PLAYER_ADDED = "player_added"
    PLAYER_UPDATED = "player_updated"
    PLAYER_REMOVED = "player_removed"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"

    # special event type to match all events
    MATCH_ALL = "match_all"


@dataclass
class SonosEventBase:
    """Representation of an Event emitted in/by Sonos."""

    event_type: EventType
    object_id: str | None = None  # optional identifier such as player id or group id
    data: Any | None = None  # optional data


@dataclass
class PlayerEvent(SonosEventBase):
    """Representation of an Event emitted when a player was added, updated or removed."""

    data: SonosPlayer


@dataclass
class GroupEvent(SonosEventBase):
    """Representation of an Event emitted when a group was added, updated or removed."""

    data: SonosGroup


SonosEvent = PlayerEvent | GroupEvent
