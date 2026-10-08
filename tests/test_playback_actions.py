"""Tests for the playback actions and status a group reports."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from aiosonos.group import PlaybackActions, SonosGroup

# availablePlaybackActions of an Era 300 playing a cloud queue (firmware 97.1)
ACTIONS = {
    "_objectType": "playbackAction",
    "canPlay": True,
    "canSkip": True,
    "canSkipBack": True,
    "canSkipToPrevious": True,
    "canSeek": False,
    "canPause": True,
    "canStop": True,
    "canRepeat": True,
    "canRepeatOne": True,
    "canCrossfade": True,
    "canShuffle": True,
}


def test_skip_actions_read_the_keys_the_player_sends() -> None:
    """The canSkip / canSkipToPrevious keys drive the skip properties, old and new names alike."""
    actions = PlaybackActions(dict(ACTIONS))

    assert actions.can_skip
    assert actions.can_skip_to_previous
    assert actions.can_skip_forward
    assert actions.can_skip_backward

    actions = PlaybackActions({**ACTIONS, "canSkip": False, "canSkipToPrevious": False})
    assert not actions.can_skip
    assert not actions.can_skip_to_previous
    assert not actions.can_skip_forward
    assert not actions.can_skip_backward


def test_skip_to_previous_falls_back_to_deprecated_key() -> None:
    """A player that only sends canSkipBack (pre-1.36.0) is still understood."""
    actions = PlaybackActions({"canSkipBack": True})

    assert actions.can_skip_to_previous


def test_new_group_reports_no_actions() -> None:
    """Before its status is read, a group allows nothing rather than failing on lookups."""
    group = SonosGroup(MagicMock(), {"id": "group1"})

    assert not group.playback_actions.can_skip
    assert not group.playback_actions.can_skip_to_previous
    assert not group.playback_actions.can_play


def test_repeated_status_event_refreshes_position_timestamp() -> None:
    """An event identical to the last one still re-bases the position extrapolation."""
    group = SonosGroup(MagicMock(), {"id": "group1"})
    status = {
        "playbackState": "PLAYBACK_STATE_PLAYING",
        "positionMillis": 1000,
        "availablePlaybackActions": {},
        "playModes": {},
    }
    group._handle_playback_status_update(dict(status))
    group._playback_status_last_updated -= 60  # pretend a minute went by

    group._handle_playback_status_update(dict(status))

    assert time.time() - group._playback_status_last_updated < 1
    assert group.position < 2
