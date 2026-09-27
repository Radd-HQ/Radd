"""Transition checks served by plugins through the kernel TRANSITION_CHECK socket.

Workflow never imports the plugin that answers a check. A disabled provider
withdraws its registration and the rules it served FAIL CLOSED
(`guards.unprovided_failure`): a gate an admin configured must not open because
a plugin was switched off. `providers()` feeds both write-validation and
evaluation, so they cannot disagree about what exists; `prepare` builds each
provider's per-item snapshot data; `state_moved` tells every provider after a
successful state change (how an approval is spent).
"""

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import sockets


def providers() -> dict[str, Any]:
    """check key -> TransitionCheckProvider, for every provider loaded NOW, in
    registration order. A provider is registered UNDER its check key, and the
    registry refuses two on one key (RADD-1456); a provider whose `check` names
    another key would let one plugin answer for another's rules, so it is refused
    here rather than re-keyed."""
    live: dict[str, Any] = {}
    for name, impl in sockets.providers(sockets.Socket.TRANSITION_CHECK).items():
        if impl.check != name:
            raise ValueError(
                f"transition check provider registered as {name!r} answers for {impl.check!r}"
            )
        live[name] = impl
    return live


async def prepare(session: AsyncSession, item, checks: Iterable[str]) -> dict[str, Any]:
    """What each named check's provider needs to judge this item — fetched once
    per evaluation. A check with no provider prepares nothing (it fails closed
    without looking)."""
    live = providers()
    return {
        check: await live[check].prepare(session, item) for check in checks if check in live
    }


async def state_moved(
    session: AsyncSession, item_id: uuid.UUID, to_state_id: uuid.UUID
) -> None:
    """A state change happened (items calls this after the move is flushed, on
    both the single-item and the cross-project path)."""
    for provider in providers().values():
        await provider.moved(session, item_id, to_state_id)
