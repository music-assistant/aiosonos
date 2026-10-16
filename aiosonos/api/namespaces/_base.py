"""Base/Model for namespace-specific Sonos controller."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from aiosonos.api import SonosLocalWebSocketsApi

_T = TypeVar("_T")

SubscribeCallbackType = Callable[[_T], None]
UnsubscribeCallbackType = Callable[[], None]

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _Subscription:
    """What one subscribe call listens with; it holds its id until used or replaced."""

    callback: SubscribeCallbackType
    error_callback: SubscribeCallbackType | None = None
    # the subscription this call took the id from, to hand it back should this call fail
    previous: _Subscription | None = None
    # its handle was used, or its subscribe failed: the id is not handed back to it
    ended: bool = False


class SonosNameSpace:
    """Base/Model for namespace-specific Sonos controller."""

    namespace: str
    event_type: str
    _event_model: _T
    _event_key: str

    def __init__(self, api: SonosLocalWebSocketsApi) -> None:
        """Handle Initialization."""
        self.api = api
        # the newest subscription to each id
        self._subscriptions: dict[str, _Subscription] = {}

    async def _handle_event(self, event: dict[str, Any], event_data: dict[str, Any]) -> None:
        """Handle incoming event from subscription."""
        if subscription := self._subscriptions.get(event[self._event_key]):
            subscription.callback(event_data)

    async def _handle_error_event(self, event: dict[str, Any], event_data: Any) -> None:
        """Forward an error event (playbackError, sessionError) to its subscription."""
        subscription = self._subscriptions.get(event.get(self._event_key))
        if subscription is not None and subscription.error_callback is not None:
            subscription.error_callback(event_data)

    async def _handle_subscribe(
        self,
        event_id: str,
        callback: SubscribeCallbackType,
        error_callback: SubscribeCallbackType | None = None,
    ) -> UnsubscribeCallbackType:
        """Handle subscription logic: the newest call to an id holds it until its handle is used."""
        previous = self._subscriptions.get(event_id)
        if previous is not None:
            _LOGGER.error("Duplicate subscription detected for %s", event_id)
        subscription = _Subscription(callback, error_callback, previous)

        def _unsubscribe() -> None:
            subscription.ended = True
            if self._subscriptions.get(event_id) is not subscription:
                # a newer subscription holds the id (or this handle was used before)
                return
            del self._subscriptions[event_id]
            self.api.send_command_no_wait(
                namespace=self.namespace,
                command="unsubscribe",
                **{self._event_key: event_id},
            )

        # listening from the call on: a reply or a handle of an older call to the same
        # id cannot take it away, and an error before the reply is not lost
        self._subscriptions[event_id] = subscription
        try:
            await self.api.send_command(
                namespace=self.namespace,
                command="subscribe",
                **{self._event_key: event_id},
            )
        except BaseException:
            subscription.ended = True
            if self._subscriptions.get(event_id) is subscription:
                # hand the id back to the newest call it was taken from that is not over
                while previous is not None and previous.ended:
                    previous = previous.previous
                if previous is None:
                    del self._subscriptions[event_id]
                else:
                    self._subscriptions[event_id] = previous
            raise
        # the id is held: nothing to hand back later
        subscription.previous = None
        return _unsubscribe
