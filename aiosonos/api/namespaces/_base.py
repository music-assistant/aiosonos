"""Base/Model for namespace-specific Sonos controller."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from aiosonos.exceptions import CommandTimeout, FailedCommand, InvalidState

if TYPE_CHECKING:
    from aiosonos.api import SonosLocalWebSocketsApi

_T = TypeVar("_T")

SubscribeCallbackType = Callable[[_T], None]
UnsubscribeCallbackType = Callable[[], None]

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, eq=False)
class _Listener:
    """What one subscribe call listens with."""

    callback: SubscribeCallbackType
    error_callback: SubscribeCallbackType | None = None


@dataclass(slots=True)
class _Subscription:
    """The listeners to one id; the speaker holds one subscription for all of them."""

    listeners: list[_Listener] = field(default_factory=list)
    # the speaker holds, or may hold, the subscription: a subscribe was accepted, or
    # ended without the speaker refusing it; released when the last listener leaves
    held: bool = False


class SonosNameSpace:
    """Base/Model for namespace-specific Sonos controller."""

    namespace: str
    event_type: str
    _event_model: _T
    _event_key: str

    def __init__(self, api: SonosLocalWebSocketsApi) -> None:
        """Handle Initialization."""
        self.api = api
        self._subscriptions: dict[str, _Subscription] = {}

    async def _handle_event(self, event: dict[str, Any], event_data: dict[str, Any]) -> None:
        """Handle incoming event from subscription."""
        if subscription := self._subscriptions.get(event[self._event_key]):
            for listener in list(subscription.listeners):
                # not to a listener stopped by one before it
                if listener in subscription.listeners:
                    self._deliver(listener.callback, event_data)

    async def _handle_error_event(self, event: dict[str, Any], event_data: Any) -> None:
        """Forward an error event (playbackError, sessionError) to its listeners."""
        if subscription := self._subscriptions.get(event.get(self._event_key)):
            for listener in list(subscription.listeners):
                if listener in subscription.listeners and listener.error_callback is not None:
                    self._deliver(listener.error_callback, event_data)

    async def _handle_subscribe(
        self,
        event_id: str,
        callback: SubscribeCallbackType,
        error_callback: SubscribeCallbackType | None = None,
    ) -> UnsubscribeCallbackType:
        """Subscribe to an id; the speaker holds one subscription for every listener to it."""
        subscription = self._subscriptions.setdefault(event_id, _Subscription())
        listener = _Listener(callback, error_callback)
        # listening from the call on: an error before the reply is not lost
        subscription.listeners.append(listener)

        def _unsubscribe() -> None:
            if self._remove_listener(event_id, listener):
                self._send_unsubscribe(event_id)

        try:
            await self.api.send_command(
                namespace=self.namespace,
                command="subscribe",
                **{self._event_key: event_id},
            )
        except BaseException as err:
            # only a refusal says the speaker took nothing from this call: unanswered,
            # cancelled or cut off, the subscribe may have gone through
            if isinstance(err, CommandTimeout) or not isinstance(err, FailedCommand):
                subscription.held = True
            if self._remove_listener(event_id, listener):
                with suppress(InvalidState):
                    self._send_unsubscribe(event_id)
            raise
        subscription.held = True
        return _unsubscribe

    def _remove_listener(self, event_id: str, listener: _Listener) -> bool:
        """Drop a listener; whether it was the last one and the speaker's subscription is to go."""
        subscription = self._subscriptions.get(event_id)
        if subscription is None or listener not in subscription.listeners:
            return False  # dropped before: a handle used twice
        subscription.listeners.remove(listener)
        if subscription.listeners:
            return False
        del self._subscriptions[event_id]
        return subscription.held

    def _send_unsubscribe(self, event_id: str) -> None:
        """Release the speaker's subscription to an id."""
        self.api.send_command_no_wait(
            namespace=self.namespace,
            command="unsubscribe",
            **{self._event_key: event_id},
        )

    def _deliver(self, callback: SubscribeCallbackType, event_data: Any) -> None:
        """Call one listener; its failure is logged so the others still get the event."""
        try:
            callback(event_data)
        except Exception:
            _LOGGER.exception("Error in a %s event listener", self.namespace)
