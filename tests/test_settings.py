"""Tests for player settings: websocket namespaces and the player."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiosonos.api import SonosLocalWebSocketsApi
from aiosonos.player import SonosPlayer

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

PLAYER = "RINCON_1"
# getPlayerSettings of a Sonos Ray (firmware 98.0)
SETTINGS: dict[str, Any] = {
    "_objectType": "playerSettings",
    "monoMode": False,
    "enableSpatialAudio": True,
    "homeTheater": {
        "_objectType": "homeTheaterOptions",
        "nightMode": False,
        "enhanceDialog": False,
        "enhanceDialogLevel": 0,
    },
    "eq": {"_objectType": "eqSettings", "treble": 0, "bass": 0, "loudness": True},
}


def _api() -> SonosLocalWebSocketsApi:
    api = SonosLocalWebSocketsApi("wss://1.2.3.4:1443/websocket/api", MagicMock())
    api.send_command = AsyncMock(return_value={})  # type: ignore[method-assign]
    return api


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            lambda api: api.settings.get_player_settings(PLAYER),
            {"namespace": "settings", "command": "getPlayerSettings", "playerId": PLAYER},
        ),
        (
            lambda api: api.home_theater.set_options(PLAYER, {"nightMode": True}),
            {
                "namespace": "homeTheater",
                "command": "setOptions",
                "playerId": PLAYER,
                "options": {"nightMode": True},
            },
        ),
    ],
)
async def test_namespace_commands(
    command: Callable[[SonosLocalWebSocketsApi], Awaitable[Any]], expected: dict[str, Any]
) -> None:
    """Each settings command is sent to the right namespace with its body."""
    api = _api()
    await command(api)
    api.send_command.assert_awaited_once_with(**expected)


def _player(channel_maps: list[list[str]] | None = None) -> SonosPlayer:
    client = MagicMock()
    client.groups = []
    client.api = _api()
    members = [{"id": "x", "channelMap": channels} for channels in channel_maps or []]
    return SonosPlayer(client, {"id": PLAYER, "name": "Ray", "zoneInfo": {"members": members}})


@pytest.mark.parametrize(
    ("channel_maps", "has_subwoofer", "has_surrounds"),
    [
        ([["LF", "RF"]], False, False),
        ([["LF", "RF"], ["SW"]], True, False),
        ([["LF", "RF"], ["LR"], ["RR"]], False, True),
        ([["LF", "RF"], ["SW"], ["LR"], ["RR"]], True, True),
        (None, False, False),
    ],
)
def test_bonded_speakers_from_channel_map(
    channel_maps: list[list[str]] | None, has_subwoofer: bool, has_surrounds: bool
) -> None:
    """A bonded sub (SW) and surrounds (LR/RR) are read from the zone's channel maps."""
    player = _player(channel_maps)
    assert player.has_subwoofer is has_subwoofer
    assert player.has_surrounds is has_surrounds


async def test_refresh_settings_signals_only_changes() -> None:
    """Polling the settings signals PLAYER_UPDATED only when they changed."""
    player = _player()
    player.client.api.settings.get_player_settings = AsyncMock(return_value=SETTINGS)

    await player.refresh_settings()
    await player.refresh_settings()

    assert player.settings == SETTINGS
    assert player.client.signal_event.call_count == 1


async def test_set_home_theater_options_keeps_applied_options() -> None:
    """The options the player reports back replace the cached home theater options."""
    player = _player()
    player._settings = SETTINGS
    applied = {**SETTINGS["homeTheater"], "nightMode": True}
    player.client.api.home_theater.set_options = AsyncMock(return_value=applied)

    await player.set_home_theater_options({"nightMode": True})

    assert player.settings is not None
    assert player.settings["homeTheater"] == applied
    assert player.settings["eq"] == SETTINGS["eq"]
    player.client.signal_event.assert_called_once()
