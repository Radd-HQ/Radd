"""The transition checks plugins contribute (RADD-1383).

Workflow evaluates its own checks (`TransitionCheck`) and reaches every other
`check` key through the kernel's TRANSITION_CHECK socket — never by importing
the plugin that answers it. `approvals` is the provider today; disabling it at
runtime withdraws its registration, and the rules it served then FAIL CLOSED
(`guards.unprovided_failure`), because a gate an admin configured must not
open because a plugin was switched off.

Three seams, one per moment in a rule's life:

* `providers()` — the live providers, keyed by check; write-validation and
  evaluation both read it, so they cannot disagree about what exists;
* `prepare(...)` — each rule-named provider's per-item data, for the snapshot;
* `state_moved(...)` — every provider is told after a successful state change
  (items calls it through `workflow.service`), which is how an approval is spent.
"""

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import sockets


def providers() -> dict[str, Any]:
    """check key -> TransitionCheckProvider, for every provider loaded NOW."""
    return {
        impl.check: impl
        for impl in sockets.providers(sockets.Socket.TRANSITION_CHECK).values()
    }


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
