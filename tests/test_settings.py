"""Tests for player settings: websocket namespaces, the UPnP client and the player."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientSession, web

from aiosonos.api import SonosLocalWebSocketsApi
from aiosonos.api.models import TvPowerState
from aiosonos.api.upnp import EqType, RoomCalibrationStatus, SonosUpnpApi
from aiosonos.exceptions import FailedCommand
from aiosonos.player import SonosPlayer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from pytest_aiohttp import AiohttpServer

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
        (
            lambda api: api.home_theater.set_tv_power_state(PLAYER, TvPowerState.STANDBY),
            {
                "namespace": "homeTheater",
                "command": "setTvPowerState",
                "playerId": PLAYER,
                "options": {"tvPowerState": "STANDBY"},
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


def _soap_reply(action: str, service: str, **values: str) -> str:
    outputs = "".join(f"<{name}>{value}</{name}>" for name, value in values.items())
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        f'<u:{action}Response xmlns:u="urn:schemas-upnp-org:service:{service}:1">'
        f"{outputs}</u:{action}Response></s:Body></s:Envelope>"
    )


UPNP_FAULT = (
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault>'
    "<faultcode>s:Client</faultcode><faultstring>UPnPError</faultstring><detail>"
    '<UPnPError xmlns="urn:schemas-upnp-org:control-1-0"><errorCode>402</errorCode>'
    "</UPnPError></detail></s:Fault></s:Body></s:Envelope>"
)


@dataclass
class UpnpRequest:
    """A request the fake speaker received."""

    path: str
    soap_action: str
    body: str


@dataclass
class FakeSpeaker:
    """A speaker answering every UPnP request with the same reply."""

    api: SonosUpnpApi
    status: int = 200
    reply: str = ""
    requests: list[UpnpRequest] = field(default_factory=list)


@pytest.fixture
async def speaker(
    aiohttp_server: AiohttpServer, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FakeSpeaker]:
    """Return a fake speaker with a UPnP client pointed at it."""

    async def _handle(request: web.Request) -> web.Response:
        fake.requests.append(
            UpnpRequest(request.path, request.headers["SOAPACTION"], await request.text())
        )
        return web.Response(status=fake.status, text=fake.reply, content_type="text/xml")

    app = web.Application()
    app.router.add_post("/{path:.*}", _handle)
    server = await aiohttp_server(app)
    monkeypatch.setattr("aiosonos.api.upnp.UPNP_PORT", server.port)
    async with ClientSession() as session:
        fake = FakeSpeaker(SonosUpnpApi(session, "127.0.0.1"))
        yield fake


async def test_upnp_call_sends_soap_and_parses_reply(speaker: FakeSpeaker) -> None:
    """A UPnP getter posts the SOAP action to the service and reads its output argument."""
    speaker.reply = _soap_reply("GetEQ", "RenderingControl", CurrentValue="3")

    assert await speaker.api.get_eq(EqType.SUB_GAIN) == 3

    request = speaker.requests[0]
    assert request.path == "/MediaRenderer/RenderingControl/Control"
    assert request.soap_action == '"urn:schemas-upnp-org:service:RenderingControl:1#GetEQ"'
    assert "<InstanceID>0</InstanceID><EQType>SubGain</EQType>" in request.body


async def test_upnp_reads_several_outputs(speaker: FakeSpeaker) -> None:
    """An action with several output arguments is read into one result."""
    speaker.reply = _soap_reply(
        "GetRoomCalibrationStatus",
        "RenderingControl",
        RoomCalibrationEnabled="0",
        RoomCalibrationAvailable="1",
    )

    assert await speaker.api.get_room_calibration_status() == RoomCalibrationStatus(
        enabled=False, available=True
    )


async def test_upnp_set_uses_on_off(speaker: FakeSpeaker) -> None:
    """DeviceProperties setters send On/Off to their own control path, without InstanceID."""
    speaker.reply = _soap_reply("SetLEDState", "DeviceProperties")

    await speaker.api.set_led_state(on=False)

    request = speaker.requests[0]
    assert request.path == "/DeviceProperties/Control"
    assert "<DesiredLEDState>Off</DesiredLEDState>" in request.body
    assert "InstanceID" not in request.body


@pytest.mark.parametrize(
    ("status", "reply", "error_code"),
    [(500, UPNP_FAULT, "402"), (404, "not found", "404")],
)
async def test_upnp_error_raises_failed_command(
    speaker: FakeSpeaker, status: int, reply: str, error_code: str
) -> None:
    """A UPnP fault or a non-XML error reply raises FailedCommand with the error code."""
    speaker.status = status
    speaker.reply = reply

    with pytest.raises(FailedCommand) as err:
        await speaker.api.set_led_state(on=True)
    assert err.value.error_code == error_code
