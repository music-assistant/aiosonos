"""Utils/helpers for aiosonos."""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING

from aiosonos.const import LOCAL_API_PORT, LOCAL_API_TOKEN

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from aiosonos.api.models import DiscoveryInfo


def create_ssl_context() -> ssl.SSLContext:
    """Create SSL context for Sonos local API connections."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def get_discovery_info(
    aiohttp_session: ClientSession,
    player_ip: str,
    port: int = LOCAL_API_PORT,
) -> DiscoveryInfo:
    """
    Get the discovery info for a player.

    :param aiohttp_session: The aiohttp session to use for the request.
    :param player_ip: The IP address of the player.
    :param port: The local API port of the player (each zone of an Amp Multi has its own).
    """
    async with aiohttp_session.get(
        f"https://{player_ip}:{port}/api/v1/players/local/info",
        headers={"X-Sonos-Api-Key": LOCAL_API_TOKEN},
        ssl=create_ssl_context(),
    ) as resp:
        resp.raise_for_status()
        discovery_info: DiscoveryInfo = await resp.json()
    return discovery_info
