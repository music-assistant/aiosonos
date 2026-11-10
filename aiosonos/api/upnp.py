"""
Minimal UPnP (SOAP) client for the Sonos settings the websockets api cannot change.

The local websockets api reads EQ settings but refuses to set them, and it has no
access at all to e.g. subwoofer/surround levels, the status light or the button lock.
Sonos speakers (S2 included) still serve these over UPnP on port 1400.

Reference (unofficial): https://sonos.svrooij.io/services
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from aiohttp import ClientError, ClientTimeout

from aiosonos.exceptions import CommandTimeout, ConnectionFailed, FailedCommand

if TYPE_CHECKING:
    from aiohttp import ClientSession

UPNP_PORT = 1400
UPNP_TIMEOUT = 10
SOAP_ENVELOPE = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
    '<u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:1">{arguments}</u:{action}>'
    "</s:Body></s:Envelope>"
)
UPNP_ERROR_NAMESPACE = "{urn:schemas-upnp-org:control-1-0}"


class UpnpService(StrEnum):
    """UPnP services of a Sonos speaker, by their control path."""

    RENDERING_CONTROL = "MediaRenderer/RenderingControl/Control"
    DEVICE_PROPERTIES = "DeviceProperties/Control"
    HT_CONTROL = "HTControl/Control"

    @property
    def service_type(self) -> str:
        """Return the UPnP service type name."""
        return self.value.split("/")[-2]


class EqType(StrEnum):
    """EQ types of RenderingControl GetEQ/SetEQ; not every speaker supports each."""

    AUDIO_DELAY = "AudioDelay"  # 0..5
    DIALOG_LEVEL = "DialogLevel"  # 0/1, or 1..4 (Arc Ultra)
    HEIGHT_CHANNEL_LEVEL = "HeightChannelLevel"  # -10..10
    MUSIC_SURROUND_LEVEL = "MusicSurroundLevel"  # -15..15
    NIGHT_MODE = "NightMode"
    SPEECH_ENHANCE_ENABLED = "SpeechEnhanceEnabled"  # Arc Ultra
    SUB_CROSSOVER = "SubCrossover"  # 50..110 Hz, Amp only
    SUB_ENABLED = "SubEnable"
    SUB_GAIN = "SubGain"  # -15..15
    SURROUND_ENABLED = "SurroundEnable"
    SURROUND_LEVEL = "SurroundLevel"  # -15..15
    SURROUND_MODE = "SurroundMode"  # 0 = ambient, 1 = full


class IrRepeaterState(StrEnum):
    """States of the IR repeater of a home theater speaker."""

    ON = "On"
    OFF = "Off"
    DISABLED = "Disabled"


class RoomCalibrationStatus(NamedTuple):
    """Trueplay status of a speaker."""

    enabled: bool
    available: bool


class SonosUpnpApi:
    """UPnP client for a single Sonos speaker."""

    def __init__(self, aiohttp_session: ClientSession, player_ip: str) -> None:
        """Initialize the UPnP client."""
        self._aiohttp_session = aiohttp_session
        self.player_ip = player_ip

    async def get_bass(self) -> int:
        """Get the bass level (-10..10)."""
        result = await self._rendering_control("GetBass")
        return int(result["CurrentBass"])

    async def set_bass(self, level: int) -> None:
        """Set the bass level (-10..10)."""
        await self._rendering_control("SetBass", DesiredBass=level)

    async def get_treble(self) -> int:
        """Get the treble level (-10..10)."""
        result = await self._rendering_control("GetTreble")
        return int(result["CurrentTreble"])

    async def set_treble(self, level: int) -> None:
        """Set the treble level (-10..10)."""
        await self._rendering_control("SetTreble", DesiredTreble=level)

    async def get_loudness(self) -> bool:
        """Get whether loudness compensation is enabled."""
        result = await self._rendering_control("GetLoudness", Channel="Master")
        return result["CurrentLoudness"] == "1"

    async def set_loudness(self, enabled: bool) -> None:
        """Enable or disable loudness compensation."""
        await self._rendering_control("SetLoudness", Channel="Master", DesiredLoudness=int(enabled))

    async def get_eq(self, eq_type: EqType) -> int:
        """
        Get the value of an EQ type; booleans are returned as 0/1.

        A speaker returns a value even for an EQ type it has no hardware for
        (e.g. SubEnable without a bonded sub), so check for the hardware first.
        """
        result = await self._rendering_control("GetEQ", EQType=eq_type)
        return int(result["CurrentValue"])

    async def set_eq(self, eq_type: EqType, value: int) -> None:
        """Set the value of an EQ type; booleans as 0/1."""
        await self._rendering_control("SetEQ", EQType=eq_type, DesiredValue=value)

    async def get_channel_volume(self, channel: str) -> int:
        """
        Get the volume (0..100) of a single channel, e.g. LF/RF for the balance.

        :param channel: The channel, e.g. Master, LF or RF.
        """
        result = await self._rendering_control("GetVolume", Channel=channel)
        return int(result["CurrentVolume"])

    async def set_channel_volume(self, channel: str, volume: int) -> None:
        """
        Set the volume (0..100) of a single channel, e.g. LF/RF for the balance.

        :param channel: The channel, e.g. LF or RF.
        :param volume: The volume of the channel.
        """
        await self._rendering_control("SetVolume", Channel=channel, DesiredVolume=volume)

    async def get_room_calibration_status(self) -> RoomCalibrationStatus:
        """Get the Trueplay status."""
        result = await self._rendering_control("GetRoomCalibrationStatus")
        return RoomCalibrationStatus(
            enabled=result["RoomCalibrationEnabled"] == "1",
            available=result["RoomCalibrationAvailable"] == "1",
        )

    async def set_room_calibration_enabled(self, enabled: bool) -> None:
        """Enable or disable Trueplay; only possible with an available calibration."""
        await self._rendering_control(
            "SetRoomCalibrationStatus", RoomCalibrationEnabled=int(enabled)
        )

    async def get_led_state(self) -> bool:
        """Get whether the status light is on."""
        result = await self._call(UpnpService.DEVICE_PROPERTIES, "GetLEDState")
        return result["CurrentLEDState"] == "On"

    async def set_led_state(self, on: bool) -> None:
        """Turn the status light on or off."""
        await self._call(UpnpService.DEVICE_PROPERTIES, "SetLEDState", DesiredLEDState=_on_off(on))

    async def get_button_lock_state(self) -> bool:
        """Get whether the buttons are locked."""
        result = await self._call(UpnpService.DEVICE_PROPERTIES, "GetButtonLockState")
        return result["CurrentButtonLockState"] == "On"

    async def set_button_lock_state(self, locked: bool) -> None:
        """Lock or unlock the buttons."""
        await self._call(
            UpnpService.DEVICE_PROPERTIES,
            "SetButtonLockState",
            DesiredButtonLockState=_on_off(locked),
        )

    async def get_ir_repeater_state(self) -> IrRepeaterState:
        """Get the IR repeater state of a home theater speaker."""
        result = await self._call(UpnpService.HT_CONTROL, "GetIRRepeaterState")
        return IrRepeaterState(result["CurrentIRRepeaterState"])

    async def set_ir_repeater_state(self, state: IrRepeaterState) -> None:
        """Set the IR repeater state of a home theater speaker."""
        await self._call(UpnpService.HT_CONTROL, "SetIRRepeaterState", DesiredIRRepeaterState=state)

    async def get_led_feedback_state(self) -> bool:
        """Get whether the status light flashes on TV remote presses."""
        result = await self._call(UpnpService.HT_CONTROL, "GetLEDFeedbackState")
        return result["LEDFeedbackState"] == "On"

    async def set_led_feedback_state(self, on: bool) -> None:
        """Set whether the status light flashes on TV remote presses."""
        await self._call(
            UpnpService.HT_CONTROL, "SetLEDFeedbackState", LEDFeedbackState=_on_off(on)
        )

    async def _rendering_control(self, action: str, **arguments: str | int) -> dict[str, str]:
        return await self._call(UpnpService.RENDERING_CONTROL, action, InstanceID=0, **arguments)

    async def _call(
        self, service: UpnpService, action: str, **arguments: str | int
    ) -> dict[str, str]:
        """Call a UPnP action and return its output arguments."""
        body = SOAP_ENVELOPE.format(
            action=action,
            service=service.service_type,
            arguments="".join(
                f"<{name}>{escape(str(value))}</{name}>" for name, value in arguments.items()
            ),
        )
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"urn:schemas-upnp-org:service:{service.service_type}:1#{action}"',
        }
        url = f"http://{self.player_ip}:{UPNP_PORT}/{service}"
        command = f"{service.service_type}:{action}"
        try:
            async with self._aiohttp_session.post(
                url, data=body, headers=headers, timeout=ClientTimeout(total=UPNP_TIMEOUT)
            ) as resp:
                status = resp.status
                text = await resp.text()
        except TimeoutError:
            raise CommandTimeout(command, UPNP_TIMEOUT) from None
        except ClientError as err:
            raise ConnectionFailed(err) from err
        try:
            # the reply of the player we sent the request to, on the local network
            root = ET.fromstring(text)  # noqa: S314
        except ET.ParseError:
            root = None
        if status != 200 or root is None:
            error_code = str(status)
            if root is not None:
                error_code = root.findtext(f".//{UPNP_ERROR_NAMESPACE}errorCode") or error_code
            msg = f"{command} UPnP error {error_code}"
            raise FailedCommand(error_code, msg)
        response = root.find(".//{*}Body/*")
        if response is None:
            return {}
        return {child.tag: child.text or "" for child in response}


def _on_off(value: bool) -> str:
    return "On" if value else "Off"
