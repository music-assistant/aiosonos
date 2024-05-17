"""Handle Groups related endpoints for Sonos."""

from __future__ import annotations

from aiosonos.api.models import GroupInfo, Groups

from ._base import SonosNameSpace, SubscribeCallbackType, UnsubscribeCallbackType


class GroupsNameSpace(SonosNameSpace):
    """Groups Namespace handlers."""

    namespace = "groups"
    event_type = "groups"
    _event_model = Groups
    _event_key = "householdId"

    async def modify_group_members(
        self,
        group_id: str,
        player_ids_to_add: list[str],
        player_ids_to_remove: list[str],
    ) -> GroupInfo:
        """
        Send modifyGroupMembers command to modify the group's members.

        Reference:
        https://docs.sonos.com/reference/groups-modifygroupmembers-groupid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="modifyGroupMembers",
            groupId=group_id,
            options={
                "playerIdsToAdd": player_ids_to_add,
                "playerIdsToRemove": player_ids_to_remove,
            },
        )

    async def set_group_members(
        self,
        group_id: str,
        player_ids: list[str],
        area_ids: list[str] | None = None,
    ) -> GroupInfo:
        """
        Send setGroupMembers command to set/replace the group's members.

        Reference:
        https://docs.sonos.com/reference/groups-setgroupmembers-groupid
        """
        options = {
            "playerIds": player_ids,
        }
        if area_ids is not None:
            options["areaIds"] = area_ids
        return await self.api.send_command(
            namespace=self.namespace,
            command="setGroupMembers",
            groupId=group_id,
            options=options,
        )

    async def get_groups(
        self,
        household_id: str,
        include_device_info: bool = False,  # noqa: FBT001, FBT002
    ) -> Groups:
        """
        Get all groups (and players) in a household.

        Reference:
        https://docs.sonos.com/reference/groups-getgroups-householdid
        """
        return await self.api.send_command(
            namespace=self.namespace,
            command="getGroups",
            householdId=household_id,
            options={
                "includeDeviceInfo": include_device_info,
            },
        )

    async def create_group(
        self,
        household_id: str,
        player_ids: list[str],
        music_context_group_id: str | None = None,
    ) -> GroupInfo:
        """
        Send createGroup command to create a new group.

        Reference:
        https://docs.sonos.com/reference/groups-creategroup-householdid
        """
        options = {
            "playerIds": player_ids,
        }
        if music_context_group_id is not None:
            options["musicContextGroupId"] = music_context_group_id
        return await self.api.send_command(
            namespace=self.namespace,
            command="createGroup",
            householdId=household_id,
            options=options,
        )

    async def subscribe(
        self,
        household_id: str,
        callback: SubscribeCallbackType,
    ) -> UnsubscribeCallbackType:
        """
        Subscribe to events in the Groups namespace for given player.

        Returns handle to unsubscribe.

        Reference:
        https://docs.sonos.com/reference/groups-subscribe-householdid
        """
        return await self._handle_subscribe(household_id, callback)
