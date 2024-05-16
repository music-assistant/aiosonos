from __future__ import annotations

from enum import StrEnum
from typing import NotRequired, Self, TypedDict

class PlayBackState(StrEnum):
    """Enum with possible playback states."""

    PLAYBACK_STATE_IDLE = "PLAYBACK_STATE_IDLE"
    PLAYBACK_STATE_BUFFERING = "PLAYBACK_STATE_BUFFERING"
    PLAYBACK_STATE_PAUSED = "PLAYBACK_STATE_PAUSED"
    PLAYBACK_STATE_PLAYING = "PLAYBACK_STATE_PLAYING"

    @classmethod
    def _missing_(cls: type, value: str) -> Self:  # noqa: ARG003
        """Handle unknown enum member."""
        return "UNKOWN"


PlayBackState("sambal")

