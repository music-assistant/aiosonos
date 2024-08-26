"""
Models/schemas for objects in the Sonos HTTP/Websockets API.

Reference: https://docs.sonos.com/docs/types
"""

from __future__ import annotations

from enum import StrEnum
from typing import NotRequired, TypedDict


class CommandMessage(TypedDict):
    """Representation of a Command message."""

    namespace: str  # e.g. 'groups'
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

    Reference: https://docs.sonos.com/docs/types#playervolume
    """

    _objectType: str  # = playerVolume
    fixed: bool
    muted: bool
    volume: int


class GroupVolume(TypedDict):
    """
    Representation of a GroupVolume object/response.

    Reference: https://docs.sonos.com/docs/types#groupvolume
    """

    _objectType: str  # = groupVolume
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
    """
    Representation of a Groups message (event or response).

    Reference: https://docs.sonos.com/docs/types#groups
    """

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


class PlaybackActions(TypedDict):
    """Representation of available playback actions."""

    _objectType: str  # = playbackAction
    canCrossfade: bool
    canPause: bool
    canPlay: bool
    canRepeat: bool
    canRepeatOne: bool
    canSeek: bool
    canShuffle: bool
    canSkip: bool
    canSkipBack: bool
    canSkipToPrevious: bool
    canStop: bool


class PlayModes(TypedDict):
    """Representation of play modes."""

    _objectType: str  # = playModes
    crossfade: NotRequired[bool]
    repeat: NotRequired[bool]
    repeatOne: NotRequired[bool]
    shuffle: NotRequired[bool]


class PlaybackStatus(TypedDict):
    """Representation of a playback status."""

    _objectType: str  # = playbackStatus
    availablePlaybackActions: PlaybackActions
    isDucking: bool
    playbackState: PlayBackState
    playModes: PlayModes
    positionMillis: int
    previousPositionMillis: int


class MusicService(StrEnum):
    """Enum with (known) possible container service Id's."""

    SPOTIFY = "9"
    MUSIC_ASSISTANT = "mass"
    TUNEIN = "303"
    QOBUZ = "31"
    YOUTUBE_MUSIC = "284"
    LOCAL_LIBRARY = "local-library"
    # TODO: complete this list with other known services


class MetadataId(TypedDict):
    """Representation of an ID, used in metadata objects."""

    _objectType: str  # = id
    serviceId: NotRequired[str]
    objectId: NotRequired[str]
    accountId: NotRequired[str]


class Service(TypedDict):
    """Representation of a service."""

    _objectType: str  # = service
    name: str
    images: NotRequired[list[Image]]


class Image(TypedDict):
    """Representation of an image."""

    _objectType: str  # = image
    url: str
    name: NotRequired[str]
    type: NotRequired[str]


class Author(TypedDict):
    """Representation of an author."""

    name: str
    id: MetadataId


class Narrator(TypedDict):
    """Representation of a narrator."""

    name: str
    id: MetadataId


class Producer(TypedDict):
    """Representation of a podcast producer."""

    name: str
    id: NotRequired[MetadataId]


class Book(TypedDict):
    """Representation of a (audio)book."""

    _objectType: str  # = book
    name: str
    chapterCount: NotRequired[int]
    author: NotRequired[Author]
    narrator: NotRequired[Narrator]
    id: NotRequired[MetadataId]


class Podcast(TypedDict):
    """Representation of a podcast."""

    name: str
    producer: NotRequired[Producer]
    id: NotRequired[MetadataId]
    explicit: NotRequired[bool]


class Album(TypedDict):
    """Representation of an album."""

    _objectType: str  # = album

    name: str


class Artist(TypedDict):
    """Representation of an artist."""

    _objectType: str  # = artist

    name: str


class Quality(TypedDict):
    """Representation of track quality."""

    _objectType: str  # = quality

    bitDepth: NotRequired[int]
    sampleRate: NotRequired[int]
    codec: NotRequired[str]
    lossless: NotRequired[bool]
    immersive: NotRequired[bool]
    replayGain: NotRequired[float]


class Track(TypedDict):
    """Representation of a track."""

    _objectType: str  # = track

    type: str
    name: str
    mediaUrl: NotRequired[str]
    images: NotRequired[list[Image]]
    contentType: NotRequired[str]
    album: NotRequired[Album]
    artist: NotRequired[Artist]
    author: NotRequired[Author]
    book: NotRequired[Book]
    narrator: NotRequired[Narrator]
    podcast: NotRequired[Podcast]
    producer: NotRequired[Producer]
    releaseDate: NotRequired[str]
    episodeNumber: NotRequired[int]
    id: NotRequired[MetadataId]
    service: NotRequired[Service]
    durationMillis: NotRequired[int]
    trackNumber: NotRequired[int]
    chapterNumber: NotRequired[int]
    explicit: NotRequired[bool]


class Show(TypedDict):
    """
    Representation of a (Radio)Show).

    Information about the current "show", when available.
    Generally only present for radio stations (container.type = "station")
    """

    _objectType: str  # = show
    name: str
    id: NotRequired[MetadataId]
    images: NotRequired[list[Image]]
    explicit: NotRequired[bool]


class PlaybackSession(TypedDict):
    """
    Representation of a PlaybackSession.

    Provides details on the external source that initiated the playback.
    """

    _objectType: str  # = show
    clientId: str
    isSuspended: bool
    accountId: str


class ContainerType(StrEnum):
    """Enum with possible container types."""

    LINEIN = "linein"
    STATION = "station"
    PLAYLIST = "playlist"
    AIRPLAY = "linein.airplay"
    PODCAST = "podcast"
    BOOK = "book"
    ARTIST = "artist"
    ALBUM = "album"
    ARTIST_LOCAL = "artist.local"
    ALBUM_LOCAL = "album.local"
    # TODO: complete this list with other known types


class Container(TypedDict):
    """
    Representation of a container.

    A container object indicating the current playback source.
    The container describes and identifies what is currently playing,
    for example, the programmed radio station, music service playlist,
    or linein source.

    If no content is loaded, the container field will not be present.
    """

    _objectType: str  # = container
    name: str
    type: str
    id: NotRequired[MetadataId]
    service: NotRequired[Service]
    images: NotRequired[list[Image]]
    book: NotRequired[Book]
    podcast: NotRequired[Podcast]
    explicit: NotRequired[bool]


class QueueItem(TypedDict):
    """Representation of a Queue item."""

    _objectType: str  # = queueItem

    class Policies(TypedDict):
        """Representation of (playback)policies."""

        canSkip: NotRequired[bool]
        canSkipToPrevious: NotRequired[bool]
        limitedSkips: NotRequired[bool]
        canSeek: NotRequired[bool]
        canSkipToItem: NotRequired[bool]
        canRepeat: NotRequired[bool]
        canRepeatOne: NotRequired[bool]
        canCrossfade: NotRequired[bool]
        canShuffle: NotRequired[bool]
        canResume: NotRequired[bool]
        pauseAtEndOfQueue: NotRequired[bool]
        refreshAuthWhilePaused: NotRequired[bool]
        showNNextTracks: NotRequired[int]
        showNPreviousTracks: NotRequired[int]
        isVisible: NotRequired[bool]
        notifyUserIntent: NotRequired[bool]
        pauseTtlSec: NotRequired[int]
        playTtlSec: NotRequired[int]
        pauseOnDuck: NotRequired[bool]

    id: str
    deleted: NotRequired[bool]
    track: NotRequired[Track]
    policies: NotRequired[Policies]


class MetadataStatus(TypedDict):
    """Representation of (playback) metadata status."""

    _objectType: str  # = metadataStatus

    container: NotRequired[Container]
    currentItem: NotRequired[QueueItem]
    nextItem: NotRequired[QueueItem]
    currentShow: NotRequired[Show]
    streamInfo: NotRequired[str]
    playbackSession: NotRequired[PlaybackSession]


class SessionStatus(TypedDict):
    """Representation of a (Playback) session status."""

    _objectType: str  # = sessionStatus

    sessionId: str
    sessionState: str  # SESSION_STATE_CONNECTED
    sessionCreated: bool
    customData: str
