"""ZeroNexus Resilient UI Components and Anti-Concurrency Debounce Engine.

Provides enterprise-grade protection against Discord rapid double-clicks,
race conditions, dead token (10062/10015/50027) cascades, and 40060 re-acknowledgment errors.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Callable, Coroutine, Optional, TypeVar

import discord

from zeronexus.ui.responder import InteractionResponder

log = logging.getLogger("zeronexus.ui.components")

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


class DebounceGuard:
    """Anti-rapid-click and anti-concurrency mutex lock for Discord interactions.
    
    Guarantees:
    1. Single in-flight execution per interactive component or view.
    2. Enforces a minimum cooldown threshold between clicks (default 0.35s).
    3. Safely ACKs throttled or duplicate clicks via safe_defer to prevent 10062 / UI hang.
    4. Automatically releases lock even if callback crashes or raises an exception.
    """

    def __init__(self, cooldown: float = 0.35) -> None:
        self.cooldown = cooldown
        self._lock = asyncio.Lock()
        self._last_trigger_ts: float = 0.0

    @property
    def is_locked(self) -> bool:
        """Returns True if an interaction is actively executing within this guard."""
        return self._lock.locked()

    async def check_and_acquire(self, interaction: Optional[discord.Interaction] = None) -> bool:
        """Attempts to acquire lock under debounce rules.
        
        If currently locked or cooldown has not elapsed:
        - Safely ACKs the interaction if provided to prevent Discord client timeout.
        - Returns False without acquiring lock.
        
        If available:
        - Acquires lock and records timestamp.
        - Returns True.
        """
        now = time.monotonic()
        if self._lock.locked() or (now - self._last_trigger_ts < self.cooldown):
            if interaction is not None:
                await InteractionResponder.safe_defer(interaction)
            return False

        await self._lock.acquire()
        self._last_trigger_ts = time.monotonic()
        return True

    def release(self) -> None:
        """Safely releases the underlying mutex lock."""
        if self._lock.locked():
            self._lock.release()

    async def __aenter__(self) -> DebounceGuard:
        await self._lock.acquire()
        self._last_trigger_ts = time.monotonic()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


class ZNButton(discord.ui.Button):
    """Resilient Button component with built-in debouncing, mutex lock, and dead token defense."""

    def __init__(
        self,
        *args: Any,
        debounce_interval: float = 0.35,
        on_debounced: Optional[Callable[[discord.Interaction], Coroutine[Any, Any, None]]] = None,
        callback: Optional[Callable[[discord.Interaction], Coroutine[Any, Any, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.guard = DebounceGuard(cooldown=debounce_interval)
        self._on_debounced = on_debounced
        self._inner_callback: Optional[Callable[[discord.Interaction], Coroutine[Any, Any, Any]]] = callback
        if callback is not None:
            super().__setattr__("callback", self._debounced_callback_dispatch)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "callback" and callable(value) and value != self._debounced_callback_dispatch:
            self._inner_callback = value
            super().__setattr__("callback", self._debounced_callback_dispatch)
            return
        super().__setattr__(name, value)

    async def _debounced_callback_dispatch(self, interaction: discord.Interaction) -> None:
        if InteractionResponder.is_interaction_expired(interaction):
            return

        if self.guard.is_locked:
            await InteractionResponder.safe_defer(interaction)
            if self._on_debounced:
                try:
                    await self._on_debounced(interaction)
                except Exception:
                    pass
            return

        can_proceed = await self.guard.check_and_acquire(interaction)
        if not can_proceed:
            if self._on_debounced:
                try:
                    await self._on_debounced(interaction)
                except Exception:
                    pass
            return

        try:
            if self._inner_callback:
                res = self._inner_callback(interaction)
                if inspect.isawaitable(res):
                    await res
            else:
                await self.on_click(interaction)
        except Exception as e:
            log.error(f"ZNButton [{getattr(self, 'custom_id', 'unknown')}] unhandled error: {e}", exc_info=True)
            await InteractionResponder.safe_error(interaction, e)
        finally:
            self.guard.release()

    async def on_click(self, interaction: discord.Interaction) -> None:
        """Override in subclass if not supplying callback attribute."""
        pass


class ZNSelect(discord.ui.Select):
    """Resilient Select menu component with built-in debouncing, mutex lock, and dead token defense."""

    def __init__(
        self,
        *args: Any,
        debounce_interval: float = 0.35,
        on_debounced: Optional[Callable[[discord.Interaction], Coroutine[Any, Any, None]]] = None,
        callback: Optional[Callable[[discord.Interaction], Coroutine[Any, Any, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.guard = DebounceGuard(cooldown=debounce_interval)
        self._on_debounced = on_debounced
        self._inner_callback: Optional[Callable[[discord.Interaction], Coroutine[Any, Any, Any]]] = callback
        if callback is not None:
            super().__setattr__("callback", self._debounced_callback_dispatch)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "callback" and callable(value) and value != self._debounced_callback_dispatch:
            self._inner_callback = value
            super().__setattr__("callback", self._debounced_callback_dispatch)
            return
        super().__setattr__(name, value)

    async def _debounced_callback_dispatch(self, interaction: discord.Interaction) -> None:
        if InteractionResponder.is_interaction_expired(interaction):
            return

        if self.guard.is_locked:
            await InteractionResponder.safe_defer(interaction)
            if self._on_debounced:
                try:
                    await self._on_debounced(interaction)
                except Exception:
                    pass
            return

        can_proceed = await self.guard.check_and_acquire(interaction)
        if not can_proceed:
            if self._on_debounced:
                try:
                    await self._on_debounced(interaction)
                except Exception:
                    pass
            return

        try:
            if self._inner_callback:
                res = self._inner_callback(interaction)
                if inspect.isawaitable(res):
                    await res
            else:
                await self.on_select(interaction)
        except Exception as e:
            log.error(f"ZNSelect [{getattr(self, 'custom_id', 'unknown')}] unhandled error: {e}", exc_info=True)
            await InteractionResponder.safe_error(interaction, e)
        finally:
            self.guard.release()

    async def on_select(self, interaction: discord.Interaction) -> None:
        """Override in subclass if not supplying callback attribute."""
        pass


def debounced_callback(cooldown: float = 0.35) -> Callable[[F], F]:
    """Decorator wrapping any interaction callback with debouncing and safe exception handling."""
    guard = DebounceGuard(cooldown=cooldown)

    def decorator(func: F) -> F:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            interaction: Optional[discord.Interaction] = None
            for arg in args:
                if isinstance(arg, discord.Interaction) or (isinstance(arg, (asyncio.Future, object)) and hasattr(arg, "response")):
                    interaction = arg
                    break
            if interaction is None:
                interaction = kwargs.get("interaction")

            if interaction is not None and InteractionResponder.is_interaction_expired(interaction):
                return None

            if guard.is_locked:
                if interaction is not None:
                    await InteractionResponder.safe_defer(interaction)
                return None

            can_proceed = await guard.check_and_acquire(interaction)
            if not can_proceed:
                return None

            try:
                return await func(*args, **kwargs)
            except Exception as e:
                log.error(f"Error in debounced callback {func.__name__}: {e}", exc_info=True)
                if interaction is not None:
                    await InteractionResponder.safe_error(interaction, e)
                return None
            finally:
                guard.release()

        return wrapper  # type: ignore[return-value]

    return decorator
