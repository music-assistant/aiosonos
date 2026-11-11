"""Tests for applying the group a group command answers with."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiosonos.client import SonosLocalApiClient
from aiosonos.const import EventType
from aiosonos.group import SonosGroup
from aiosonos.player import SonosPlayer

LEADER = "RINCON_LEADER000001400"
MEMBER = "RINCON_MEMBER000001400"
OTHER = "RINCON_OTHER0000001400"
LEADER_GROUP = f"{LEADER}:1000000001"
MEMBER_GROUP = f"{MEMBER}:1000000002"
OTHER_GROUP = f"{OTHER}:1000000003"


def _group(group_id: str, coordinator: str, player_ids: list[str], name: str) -> dict[str, Any]:
    """Build a group entry as the speaker sends it in a reply or a groups event."""
    return {
        "_objectType": "group",
        "id": group_id,
        "name": name,
        "coordinatorId": coordinator,
        "playerIds": player_ids,
    }


def _reply(player_ids: list[str], name: str, group_id: str = LEADER_GROUP) -> dict[str, Any]:
    """Build the groupInfo a modifyGroupMembers or setGroupMembers command answers with."""
    # the speaker lists a new member ahead of the coordinator here
    return {"_objectType": "groupInfo", "group": _group(group_id, LEADER, player_ids, name)}


def _groups_event(*groups: dict[str, Any]) -> dict[str, Any]:
    """Build a groups event of the whole household."""
    return {
        "_objectType": "groups",
        "groups": list(groups),
        "partial": False,
        "players": [
            {"_objectType": "player", "id": player_id, "name": player_id}
            for player_id in (LEADER, MEMBER, OTHER)
        ],
    }


GROUPED = _group(LEADER_GROUP, LEADER, [LEADER, MEMBER], "Leader + 1")
ALONE = _group(LEADER_GROUP, LEADER, [LEADER], "Leader")
MEMBER_ALONE = _group(MEMBER_GROUP, MEMBER, [MEMBER], "Member")
OTHER_ALONE = _group(OTHER_GROUP, OTHER, [OTHER], "Other")


def _leader_client(*groups: dict[str, Any]) -> SonosLocalApiClient:
    """Create the client of the leader, set up from the given household."""
    client = SonosLocalApiClient("1.2.3.4", MagicMock())
    client._player_id = LEADER
    client._loop = asyncio.get_running_loop()
    client.signal_event = MagicMock()
    client.api = MagicMock()
    client._groups = {data["id"]: SonosGroup(client, dict(data)) for data in groups}
    for group in client._groups.values():
        # set up already: subscribed to its own status
        group._unsubscribe_callbacks = [MagicMock()]
    client._player = SonosPlayer(client, {"id": LEADER, "name": "Leader"})
    return client


def _updated(client: SonosLocalApiClient, group_id: str) -> int:
    """Count the GROUP_UPDATED events signalled for a group."""
    return sum(
        1
        for call in client.signal_event.call_args_list
        if call.args[0].event_type == EventType.GROUP_UPDATED and call.args[0].object_id == group_id
    )


async def test_an_added_member_is_in_the_group_when_the_command_returns() -> None:
    """The reply lists the new member; the groups event that follows seconds later agrees."""
    client = _leader_client(ALONE, MEMBER_ALONE, OTHER_ALONE)
    client.api.groups.modify_group_members = AsyncMock(
        return_value=_reply([MEMBER, LEADER], "Leader + 1")
    )

    await client.player.group.modify_group_members([MEMBER], [])

    assert client.player.group_members == [LEADER, MEMBER]
    assert client.player.group.name == "Leader + 1"
    assert client.player.is_coordinator
    assert client._groups[MEMBER_GROUP].player_ids == []
    assert _updated(client, LEADER_GROUP) == 1

    client._handle_groups_event(_groups_event(GROUPED, OTHER_ALONE))

    assert client.player.group_members == [LEADER, MEMBER]
    assert MEMBER_GROUP not in client._groups
    assert _updated(client, LEADER_GROUP) == 1


async def test_a_removed_member_is_out_of_the_group_when_the_command_returns() -> None:
    """The reply leaves the removed member out; the groups event that follows agrees."""
    client = _leader_client(GROUPED, OTHER_ALONE)
    client.api.groups.modify_group_members = AsyncMock(return_value=_reply([LEADER], "Leader"))

    await client.player.group.modify_group_members([], [MEMBER])

    assert client.player.group_members == [LEADER]
    assert _updated(client, LEADER_GROUP) == 1

    client._handle_groups_event(_groups_event(ALONE, MEMBER_ALONE, OTHER_ALONE))

    assert client.player.group_members == [LEADER]
    assert _updated(client, LEADER_GROUP) == 1


async def test_set_group_members_applies_the_reply() -> None:
    """The group setGroupMembers answers with is applied when the command returns."""
    client = _leader_client(ALONE, MEMBER_ALONE, OTHER_ALONE)
    client.api.groups.set_group_members = AsyncMock(
        return_value=_reply([MEMBER, LEADER], "Leader + 1")
    )

    await client.player.group.set_group_members([LEADER, MEMBER])

    assert client.player.group_members == [LEADER, MEMBER]


async def test_a_reply_for_another_group_is_left_to_the_groups_event() -> None:
    """A group under another id than the one commanded is not applied from the reply."""
    client = _leader_client(ALONE, MEMBER_ALONE, OTHER_ALONE)
    client.api.groups.modify_group_members = AsyncMock(
        return_value=_reply([MEMBER, LEADER], "Leader + 1", group_id=f"{LEADER}:1000000009")
    )

    await client.player.group.modify_group_members([MEMBER], [])

    assert client.player.group_members == [LEADER]
    assert set(client._groups) == {LEADER_GROUP, MEMBER_GROUP, OTHER_GROUP}
    client.signal_event.assert_not_called()


@pytest.mark.parametrize(
    "reply",
    [None, {}, {"_objectType": "groupInfo"}, {"group": {"id": LEADER_GROUP}}],
)
async def test_a_reply_without_the_group_is_left_to_the_groups_event(reply: Any) -> None:
    """A reply that does not carry the resulting group changes nothing and fails nothing."""
    client = _leader_client(ALONE, MEMBER_ALONE, OTHER_ALONE)
    client.api.groups.modify_group_members = AsyncMock(return_value=reply)

    await client.player.group.modify_group_members([MEMBER], [])

    assert client.player.group_members == [LEADER]
    client.signal_event.assert_not_called()
