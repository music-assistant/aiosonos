"""Tests for setting up a group this player coordinates, and retrying when that fails."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from aiosonos import client as client_module
from aiosonos.client import SonosLocalApiClient
from aiosonos.const import EventType
from aiosonos.exceptions import FailedCommand
from aiosonos.group import SonosGroup

PLAYER = "RINCON_ME"
OTHER = "RINCON_OTHER"


def _api(*, fail_subscribe: int | None = None, error: Exception | None = None) -> MagicMock:
    """Build a mocked API whose n-th subscribe (1-based) raises `error`."""
    api = MagicMock()
    api.group_volume.get_volume = AsyncMock(return_value={})
    api.playback.get_playback_status = AsyncMock(
        return_value={"availablePlaybackActions": {}, "playModes": {}},
    )
    api.playback_metadata.get_metadata_status = AsyncMock(return_value={})
    subscribes = [api.playback, api.group_volume, api.playback_metadata]
    for number, namespace in enumerate(subscribes, start=1):
        if number == fail_subscribe:
            namespace.subscribe = AsyncMock(side_effect=error)
        else:
            namespace.subscribe = AsyncMock(return_value=Mock())
    return api


def _client() -> SonosLocalApiClient:
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._player_id = PLAYER
    client._loop = asyncio.get_running_loop()
    client.signal_event = MagicMock()
    client._player = MagicMock()
    return client


def _group(client: SonosLocalApiClient, coordinator: str) -> SonosGroup:
    return SonosGroup(client, {"id": "group1", "coordinatorId": coordinator, "playerIds": [PLAYER]})


async def test_remote_group_is_left_unsubscribed_quietly() -> None:
    """A group this player does not coordinate cannot be subscribed to; that is not an error."""
    client = _client()
    client.api = _api(fail_subscribe=1, error=FailedCommand("groupCoordinatorChanged"))
    group = _group(client, OTHER)

    await group.async_init()

    assert not group.is_subscribed
    assert not group.coordinated_by_client


async def test_coordinator_refusal_on_own_group_is_raised() -> None:
    """The same refusal for a group this player coordinates is transient and must be retried."""
    client = _client()
    client.api = _api(fail_subscribe=1, error=FailedCommand("groupCoordinatorChanged"))
    group = _group(client, PLAYER)

    with pytest.raises(FailedCommand):
        await group.async_init()

    assert not group.is_subscribed


async def test_partial_subscription_is_undone_on_failure() -> None:
    """A subscribe that fails after an earlier one succeeded unsubscribes the earlier one."""
    client = _client()
    client.api = _api(fail_subscribe=2, error=FailedCommand("ERROR_SOMETHING"))
    group = _group(client, PLAYER)
    first_unsubscribe = client.api.playback.subscribe.return_value

    with pytest.raises(FailedCommand):
        await group.async_init()

    first_unsubscribe.assert_called_once()
    assert group._unsubscribe_callbacks == []


async def test_connection_failure_is_undone_and_raised() -> None:
    """A non-command failure mid-setup also undoes what was subscribed."""
    client = _client()
    client.api = _api(fail_subscribe=3, error=ConnectionError("gone"))
    group = _group(client, PLAYER)

    with pytest.raises(ConnectionError):
        await group.async_init()

    client.api.playback.subscribe.return_value.assert_called_once()
    client.api.group_volume.subscribe.return_value.assert_called_once()
    assert group._unsubscribe_callbacks == []


async def test_failed_setup_is_retried_then_announced_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A setup that fails once is retried after the first delay and announced once."""
    monkeypatch.setattr(client_module, "SETUP_RETRY_DELAYS", (0,))
    client = _client()
    group = _group(client, PLAYER)
    client._groups = {"group1": group}
    group.async_init = AsyncMock(side_effect=[FailedCommand("groupCoordinatorChanged"), None])

    await client._setup_group({"id": "group1"})
    assert "group1" in client._group_setups, "a retry is pending"
    await client._group_setups["group1"]

    assert group.async_init.await_count == 2
    client._player.check_active_group.assert_called_once()
    client.signal_event.assert_called_once()
    assert client.signal_event.call_args.args[0].event_type == EventType.GROUP_ADDED
    assert "group1" not in client._group_setups


async def test_setup_gives_up_after_the_last_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """When every attempt fails the group stays registered, so a later groups event can retry."""
    monkeypatch.setattr(client_module, "SETUP_RETRY_DELAYS", (0, 0))
    client = _client()
    group = _group(client, PLAYER)
    client._groups = {"group1": group}
    group.async_init = AsyncMock(side_effect=FailedCommand("groupCoordinatorChanged"))

    await client._setup_group({"id": "group1"})
    await client._group_setups["group1"]

    assert group.async_init.await_count == 3
    client.signal_event.assert_not_called()
    assert client._groups["group1"] is group


async def test_groups_event_sets_up_an_unsubscribed_own_group_once() -> None:
    """An existing group this player now coordinates, with no subscriptions, is set up once."""
    client = _client()
    group = _group(client, OTHER)
    client._groups = {"group1": group}
    group.async_init = AsyncMock()
    data = {"id": "group1", "coordinatorId": PLAYER, "playerIds": [PLAYER]}
    event = {"groups": [data], "players": [{"id": PLAYER}]}

    client._handle_groups_event(event)
    client._handle_groups_event(event)
    task = client._group_setups["group1"]
    await task

    group.async_init.assert_awaited_once()
    assert group.coordinated_by_client


async def test_groups_event_leaves_a_subscribed_group_alone() -> None:
    """A group that already has its subscriptions is not set up again."""
    client = _client()
    group = _group(client, PLAYER)
    group._unsubscribe_callbacks = [Mock()]
    client._groups = {"group1": group}
    group.async_init = AsyncMock()

    client._handle_groups_event(
        {
            "groups": [{"id": "group1", "coordinatorId": PLAYER, "playerIds": [PLAYER]}],
            "players": [],
        },
    )

    assert "group1" not in client._group_setups
    group.async_init.assert_not_awaited()


async def test_group_removed_while_retry_pending_cancels_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A group removed during its retry wait is cleaned up and the retry cancelled."""
    monkeypatch.setattr(client_module, "SETUP_RETRY_DELAYS", (60,))
    client = _client()
    group = _group(client, PLAYER)
    client._groups = {"group1": group}
    group.async_init = AsyncMock(side_effect=FailedCommand("groupCoordinatorChanged"))
    group.cleanup = Mock()

    await client._setup_group({"id": "group1"})
    task = client._group_setups["group1"]
    client._handle_groups_event({"groups": [], "players": []})
    await asyncio.sleep(0)

    assert task.cancelled()
    group.cleanup.assert_called_once()
    assert "group1" not in client._groups
    assert client.signal_event.call_args.args[0].event_type == EventType.GROUP_REMOVED
