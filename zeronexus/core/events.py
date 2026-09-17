"""ZeroNexus Internal Asynchronous Event Bus.

Allows decoupled modules to publish and subscribe to both Discord Gateway events
and internal lifecycle signals without direct dependencies.
Exceptions in subscribers are caught and logged to preserve system stability.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from typing import Any, Callable, Coroutine, Dict, List

from zeronexus.core.logger import log

EventListener = Callable[..., Coroutine[Any, Any, None]]


class EventBus:
    """Non-blocking, exception-isolated asynchronous event dispatcher."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventListener]] = defaultdict(list)
        self._event_counts: Dict[str, int] = defaultdict(int)

    def subscribe(self, event_name: str) -> Callable[[EventListener], EventListener]:
        """Decorator to register an asynchronous event handler."""
        def decorator(func: EventListener) -> EventListener:
            self.register(event_name, func)
            return func
        return decorator

    def register(self, event_name: str, callback: EventListener) -> None:
        """Registers a listener for a specific event name."""
        if not inspect.iscoroutinefunction(callback):
            raise TypeError(f"Event listener for '{event_name}' must be an async coroutine function.")
        if callback not in self._subscribers[event_name]:
            self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: EventListener) -> bool:
        """Removes a registered listener."""
        if event_name in self._subscribers and callback in self._subscribers[event_name]:
            self._subscribers[event_name].remove(callback)
            return True
        return False

    async def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """Emits an event concurrently to all subscribers, isolating individual subscriber errors."""
        self._event_counts[event_name] += 1
        listeners = self._subscribers.get(event_name, [])
        if not listeners:
            return

        tasks = [self._safe_invoke(listener, event_name, *args, **kwargs) for listener in listeners]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_invoke(self, listener: EventListener, event_name: str, *args: Any, **kwargs: Any) -> None:
        try:
            await listener(*args, **kwargs)
        except Exception as e:
            listener_name = getattr(listener, "__qualname__", str(listener))
            log.error(f"Error in event listener '{listener_name}' on event '{event_name}': {e}", exc_info=True)

    def get_subscriber_count(self, event_name: str | None = None) -> int:
        if event_name:
            return len(self._subscribers.get(event_name, []))
        return sum(len(listeners) for listeners in self._subscribers.values())

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_events_emitted": sum(self._event_counts.values()),
            "distinct_events": len(self._subscribers),
            "total_listeners": self.get_subscriber_count(),
            "event_counts": dict(self._event_counts),
        }


# Singleton Event Bus instance
event_bus = EventBus()
