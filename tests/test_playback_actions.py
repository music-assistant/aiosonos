"""Tests for the PlaybackActions wrapper."""

from __future__ import annotations

from aiosonos.group import PlaybackActions


def test_skip_actions_read_sonos_keys() -> None:
    """The skip properties reflect the keys Sonos sends in availablePlaybackActions."""
    actions = PlaybackActions({"canSkip": True, "canSkipBack": True})

    assert actions.can_skip_forward
    assert actions.can_skip_backward
    assert not PlaybackActions({}).can_skip_forward
