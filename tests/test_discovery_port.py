"""Tests for the local API port used to fetch a player's discovery info."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aiosonos import client as client_module
from aiosonos.client import SonosLocalApiClient
from aiosonos.utils import get_discovery_info

DISCOVERY = {"playerId": "player1", "householdId": "household1", "websocketUrl": "wss://host"}


def _session() -> MagicMock:
    resp = MagicMock()
    resp.json = AsyncMock(return_value=DISCOVERY)
    session = MagicMock()
    session.get.return_value.__aenter__.return_value = resp
    return session


async def test_discovery_info_is_fetched_on_the_default_port() -> None:
    """Without a port, the discovery info comes from the standard local API port 1443."""
    session = _session()

    assert await get_discovery_info(session, "1.2.3.4") == DISCOVERY

    assert session.get.call_args.args[0] == "https://1.2.3.4:1443/api/v1/players/local/info"


async def test_discovery_info_is_fetched_on_the_given_port() -> None:
    """A zone of a multi-zone device answers on its own port."""
    session = _session()

    await get_discovery_info(session, "1.2.3.4", 1444)

    assert session.get.call_args.args[0] == "https://1.2.3.4:1444/api/v1/players/local/info"


@pytest.mark.parametrize(("kwargs", "port"), [({}, 1443), ({"port": 1445}, 1445)])
async def test_the_client_fetches_its_discovery_info_on_its_own_port(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, int],
    port: int,
) -> None:
    """connect() asks the player for its discovery info on the port the client was given."""
    session = MagicMock()
    client = SonosLocalApiClient("1.2.3.4", session, **kwargs)
    discovery = AsyncMock(return_value=DISCOVERY)
    monkeypatch.setattr(client_module, "get_discovery_info", discovery)
    api = MagicMock()
    api.connect = AsyncMock()
    monkeypatch.setattr(client_module, "SonosLocalWebSocketsApi", MagicMock(return_value=api))

    await client.connect()

    assert client.port == port
    discovery.assert_awaited_once_with(session, "1.2.3.4", port)
    assert client.player_id == "player1"
