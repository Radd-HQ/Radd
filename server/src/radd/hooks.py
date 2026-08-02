"""In-transaction hooks: a module reacts to another module's mutation atomically.

Distinct from the events outbox: hook handlers run inside the emitting transaction and
commit or roll back with it. Use them only when the reaction must be atomic with the
trigger (e.g. seeding a project's default states). Everything else belongs to outbox
consumers, which run after commit.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[AsyncSession, Any], Awaitable[None]]


class HookRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event_type: StrEnum) -> Callable[[Handler], Handler]:
        def register(handler: Handler) -> Handler:
            self._handlers[str(event_type)].append(handler)
            return handler

        return register

    async def dispatch(self, session: AsyncSession, event_type: StrEnum, subject: Any) -> None:
        for handler in self._handlers[str(event_type)]:
            await handler(session, subject)


hooks = HookRegistry()
