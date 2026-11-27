"""Tests for the queue item the playback status names."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

from aiosonos.client import SonosLocalApiClient
from aiosonos.group import SonosGroup

if TYPE_CHECKING:
    from aiosonos.api.models import MetadataStatus, PlaybackStatus

PLAYER = "RINCON_F0F6C1CC8D0401400"


def _status(item_id: str | None) -> PlaybackStatus:
    """Build a playbackStatus event of a playing group."""
    status: dict[str, Any] = {
        "_objectType": "playbackStatus",
        "availablePlaybackActions": {"canPause": True},
        "isDucking": False,
        "playbackState": "PLAYBACK_STATE_PLAYING",
        "playModes": {"repeat": False},
        "positionMillis": 0,
        "previousPositionMillis": 0,
    }
    if item_id is not None:
        status["itemId"] = item_id
    return cast("PlaybackStatus", status)


def _group() -> SonosGroup:
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._player_id = PLAYER
    client.signal_event = MagicMock()
    return SonosGroup(client, {"id": "group1", "coordinatorId": PLAYER, "playerIds": [PLAYER]})


def test_follows_the_status() -> None:
    """The id is the one of the latest playback status."""
    group = _group()
    assert group.playback_item_id is None

    group._handle_playback_status_update(_status("item1"))
    assert group.playback_item_id == "item1"

    group._handle_playback_status_update(_status("item2"))
    assert group.playback_item_id == "item2"


def test_none_without_an_item() -> None:
    """A status that names no item gives None, also after one that did."""
    group = _group()
    group._handle_playback_status_update(_status("item1"))

    group._handle_playback_status_update(_status(None))

    assert group.playback_item_id is None


def test_names_the_new_item_before_the_metadata() -> None:
    """At a change of track the id is the new item while the metadata still names the old one."""
    group = _group()
    group._handle_metadata_status_update(
        cast(
            "MetadataStatus",
            {"_objectType": "metadataStatus", "currentItem": {"id": "item1"}},
        )
    )
    group._handle_playback_status_update(_status("item1"))

    group._handle_playback_status_update(_status("item2"))

    assert group.playback_item_id == "item2"
    assert group.playback_metadata["currentItem"]["id"] == "item1"
