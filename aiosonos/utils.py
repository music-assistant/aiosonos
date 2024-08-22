"""Utils/helpers for aiosonos."""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING

from aiosonos.const import LOCAL_API_TOKEN

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from aiosonos.api.models import DiscoveryInfo


async def get_discovery_info(
    aiohttp_session: ClientSession,
    player_ip: str,
) -> DiscoveryInfo:
    """Get the discovery info for a player."""
    async with aiohttp_session.get(
        f"https://{player_ip}:1443/api/v1/players/local/info",
        headers={"X-Sonos-Api-Key": LOCAL_API_TOKEN},
        ssl=ssl.SSLContext(ssl.PROTOCOL_TLSv1_2),
    ) as resp:
        resp.raise_for_status()
        discovery_info: DiscoveryInfo = await resp.json()
    return discovery_info
