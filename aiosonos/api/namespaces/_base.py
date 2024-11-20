"""Base/Model for namespace-specific Sonos controller."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from aiosonos.api import SonosLocalWebSocketsApi

_T = TypeVar("_T")

SubscribeCallbackType = Callable[[_T], None]
UnsubscribeCallbackType = Callable[[], None]

_LOGGER = logging.getLogger(__name__)


class SonosNameSpace:
    """Base/Model for namespace-specific Sonos controller."""

    namespace: str
    event_type: str
    _event_model: _T
    _event_key: str

    def __init__(self, api: SonosLocalWebSocketsApi) -> None:
        """Handle Initialization."""
        self.api = api
        self._listeners: dict[str, SubscribeCallbackType] = {}

    async def _handle_event(self, event: dict[str, Any], event_data: dict[str, Any]) -> None:
        """Handle incoming event from subscription."""
        event_id = event[self._event_key]
        if handler := self._listeners.get(event_id):
            handler(event_data)

    async def _handle_subscribe(
        self,
        event_id: str,
        callback: SubscribeCallbackType,
    ) -> UnsubscribeCallbackType:
        """Handle subscription logic."""
        if event_id in self._listeners:
            _LOGGER.error("Duplicate subscription detected for %s", event_id)
        await self.api.send_command(
            namespace=self.namespace,
            command="subscribe",
            **{self._event_key: event_id},
        )
        self._listeners[event_id] = callback

        def _unsubscribe() -> None:
            self._listeners.pop(event_id)
            self.api.send_command_no_wait(
                namespace=self.namespace,
                command="unsubscribe",
                **{self._event_key: event_id},
            )

        return _unsubscribe
