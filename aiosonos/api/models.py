"""
Models/schemas for objects in the Sonos HTTP/Websockets API.

Reference: https://docs.sonos.com/docs/types
"""
from __future__ import annotations

from enum import StrEnum
from typing import NotRequired, TypedDict


class CommandMessage(TypedDict):
    """Representation of a Command message."""

    namespace: str  # e.g. 'groups:1'
    command: str  # e.g. 'getGroups'
    sessionId: NotRequired[str]  # optional sessionId parameter to pass along
    cmdId: NotRequired[str]  # optional cmdId to pass along
    # other command specific parameters are just added to this dict


class ErrorResponse(TypedDict):
    """Representation of an error response message."""

    errorCode: str  # e.g. '401'
    reason: NotRequired[str]  # e.g. 'ERROR_INVALID_PARAMETER'


class ResultMessage(TypedDict):
    """Base Representation of a message received from the api/server to the client."""

    namespace: str  # the namespace the command was directed to
    response: str  # the command that was executed
    householdId: str  # housholdId is always returned in a response
    type: str  # an optional response type
    sessionId: NotRequired[str]  # optional sessionId parameter to pass along
    cmdId: NotRequired[str]  # optional cmdId to pass along
    success: NotRequired[bool]  # in case of a command response


class AudioClipPriority(StrEnum):
    """
    Enum with possible AudioClip priorities.

    Reference: https://docs.sonos.com/reference/audioclip-loadaudioclip-playerid
    """

    LOW = "LOW"
    HIGH = "HIGH"


class AudioClipType(StrEnum):
    """
    Enum with possible AudioClip types.

    Reference: https://docs.sonos.com/reference/audioclip-loadaudioclip-playerid
    """

    CHIME = "CHIME"
    CUSTOM = "CUSTOM"
    VOICE_ASSISTANT = "VOICE_ASSISTANT"


class AudioClipLEDBehavior(StrEnum):
    """
    Enum with possible LEDBehavior behaviors.

    Reference: https://docs.sonos.com/reference/audioclip-loadaudioclip-playerid
    """

    WHITE_LED_QUICK_BREATHING = "WHITE_LED_QUICK_BREATHING"
    NONE = "NONE"


class AudioClipStatus(StrEnum):
    """
    Enum with possible LEDBehavior behaviors.

    Reference: https://docs.sonos.com/reference/audioclip-loadaudioclip-playerid
    """

    ACTIVE = "ACTIVE"
    DONE = "DONE"
    DISMISSED = "DISMISSED"
    INACTIVE = "INACTIVE"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


class AudioClip(TypedDict):
    """
    Representation of an AudioClip object/response.

    Response message from loadAudioClip command.
    Reference: https://docs.sonos.com/reference/audioclip-loadaudioclip-playerid
    """

    _objectType: str  # = audioClip
    id: str  # The unique identifier for the audio clip.
    name: str  # User identifiable string.
    appId: str  # The unique identifier for the app that created the audio clip.
    priority: AudioClipPriority
    clipType: AudioClipType  # e.g. 'CHIME'
    status: AudioClipStatus  # This field indicates the state of the audio clip
    clipLEDBehavior: AudioClipLEDBehavior  # e.g. 'WHITE_LED_QUICK_BREATHING'


class AudioClipStatusEvent(TypedDict):
    """
    Representation of an AudioClipStatus message, as received in events.

    Reference: https://docs.sonos.com/reference/audioclip-subscribe-playerid
    """

    _objectType: str  # = audioClipStatus
    audioClips: list[AudioClip]


class PlayerVolume(TypedDict):
    """
    Representation of a PlayerVolume object/response.

    Response message from loadAudioClip command.
    Reference: https://docs.sonos.com/reference/audioclip-loadaudioclip-playerid
    """

    _objectType: str  # = playerVolume
    fixed: bool
    muted: bool
    volume: int


class PlayBackState(StrEnum):
    """Enum with possible playback states."""

    PLAYBACK_STATE_IDLE = "PLAYBACK_STATE_IDLE"
    PLAYBACK_STATE_BUFFERING = "PLAYBACK_STATE_BUFFERING"
    PLAYBACK_STATE_PAUSED = "PLAYBACK_STATE_PAUSED"
    PLAYBACK_STATE_PLAYING = "PLAYBACK_STATE_PLAYING"


class SonosCapability(StrEnum):
    """Enum with possible Sonos (device) capabilities."""

    CLOUD = "CLOUD"
    PLAYBACK = "PLAYBACK"
    AIRPLAY = "AIRPLAY"
    LINE_IN = "LINE_IN"
    VOICE = "VOICE"
    AUDIO_CLIP = "AUDIO_CLIP"
    MICROPHONE_SWITCH = "MICROPHONE_SWITCH"


class Group(TypedDict):
    """Representation of a group."""

    _objectType: str  # = group
    coordinatorId: str
    id: str
    name: str
    playbackState: NotRequired[str]
    playerIds: list[str]
    areaIds: NotRequired[list[str]]


class GroupInfo(TypedDict):
    """Representation of a GroupInfo object/event."""

    _objectType: str  # = groupInfo
    group: Group


class Player(TypedDict):
    """Representation of a player."""

    _objectType: str  # = player
    id: str
    name: str
    websocketUrl: str
    softwareVersion: str
    apiVersion: str
    minApiVersion: str
    devices: list[DeviceInfo]
    zoneInfo: ActiveZone


class DeviceInfo(TypedDict):
    """Representation of device information."""

    _objectType: str  # = deviceInfo
    id: str
    primaryDeviceId: NotRequired[str]
    serialNumber: NotRequired[str]
    modelDisplayName: NotRequired[str]
    color: NotRequired[str]
    capabilities: list[SonosCapability]
    apiVersion: NotRequired[str]
    minApiVersion: NotRequired[str]
    name: NotRequired[str]
    websocketUrl: NotRequired[str]
    softwareVersion: NotRequired[str]
    hwVersion: NotRequired[str]
    swGen: NotRequired[int]


class ZoneMemberState(TypedDict):
    """Representation of a zone member state."""

    _objectType: str  # = zoneMemberState
    disconnected: bool


class ActiveZoneMember(TypedDict):
    """Representation of an active zone member."""

    _objectType: str  # = activeZoneMember
    channelMap: list[str]
    id: str
    state: ZoneMemberState


class ActiveZone(TypedDict):
    """Representation of an active zone."""

    _objectType: str  # = activeZone
    members: list[ActiveZoneMember]
    name: str
    zoneId: NotRequired[str]


class Groups(TypedDict):
    """Representation of a Groups message (event or response)."""

    _objectType: str  # = groups
    groups: list[Group]
    partial: bool
    players: list[Player]


class DiscoveryInfo(TypedDict):
    """Representation of discoveryInfo."""

    _objectType: str  # = discoveryInfo
    device: DeviceInfo
    householdId: str
    locationId: str
    playerId: str
    groupId: str
    websocketUrl: str
    restUrl: str
