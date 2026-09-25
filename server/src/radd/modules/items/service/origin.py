"""Where a new issue came from (RADD-1320) — a scope, not a parameter.

The creating door (mail intake, a form, the portal, Alertmanager) knows its
origin; the create call itself can be several frames down (forms go through
automations' intake validation first). A ContextVar scope carries it there the
way `events.quiet()` carries silence, with no signature in between changing.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum

from radd.modules.events import service as events

from ..enums import ItemOrigin

_origin: ContextVar[str | None] = ContextVar("item_origin", default=None)


@contextmanager
def creating_from(origin: StrEnum) -> Iterator[None]:
    token = _origin.set(str(origin))
    try:
        yield
    finally:
        _origin.reset(token)


def current_origin() -> str | None:
    """The stated origin, else `automation` inside an automated scope."""
    stated = _origin.get()
    if stated is not None:
        return stated
    return ItemOrigin.AUTOMATION.value if events.is_automated() else None
