"""
Manage a Sonos Topology/Household using HTTP or Websockets API.

Simple wrapper for the Websocket API provided by Sonos which runs in the cloud,
but also locally on every Sonos speaker.

API Reference can be found here:
https://docs.sonos.com/reference
"""

from ._base import AbstractSonosApi  # noqa: F401
from .websockets import SonosLocalWebSocketsApi  # noqa: F401
