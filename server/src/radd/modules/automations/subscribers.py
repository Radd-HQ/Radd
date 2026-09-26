"""The `item.creating` hook handler — required-mode enforcement (spec 119).

The savepoint endpoint is what a person's Submit goes through. This is what
everything ELSE goes through: `POST /items`, the MCP `create_item` tool, an
extension, a script. A validation rule an admin marked REQUIRED that only the
web form obeyed would not be a rule, it would be a suggestion with a nice
interface.

Registered here rather than reached for by `items`, because the dependency has
exactly one legal direction: `automations` already depends on `items`, so it is
the side that gets to know both names.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.kernel.registry import registries
from radd.modules.events import service as events
from radd.modules.items.hooks import ItemCreating, ItemHook

from . import intake
from .validation import DraftScope

logger = logging.getLogger(__name__)


#: This module's id in the kernel registry — the same string the plugin declares.
_PLUGIN_ID = "automations"


def is_enabled() -> bool:
    """Whether this module is still MOUNTED.

    `HookRegistry.on()` appends and nothing takes it back, so a hot-disabled
    automations plugin would go on refusing creations from a handler nobody can
    reach to unregister: rules still biting after the module that owns them was
    turned off, which is the one thing disabling a plugin has to mean.

    Asked of the kernel registry rather than kept as a flag of our own —
    The boot loader omits disabled plugins there, and `ai.features.
    plugin_loaded` is the same question asked the same way. A private flag would
    be a second copy of that fact, and a lifecycle hook is the wrong place to
    keep it: it is per-PROCESS, so an app teardown anywhere would leave the next
    caller unenforced.
    """
    return _PLUGIN_ID in registries.plugins


@hooks.on(ItemHook.CREATING)
async def enforce_required_validation(session: AsyncSession, subject: ItemCreating) -> None:
    """Refuse a creation that fails a REQUIRED check.

    Skipped for: the savepoint flow's own inner create (it validates one level
    up, advisory bindings included); `events.automated()` (an automation's own
    output is not intake); `events.quiet()` (imports are history); and machine
    intake wrapped in `intake.suppressed()` (mail poller, Alertmanager — a
    refusal there drops a request with no bounce, or 5xxs forever).
    Only REQUIRED bindings run: advisory findings have no one to show them to.
    """
    if not is_enabled():
        return
    if intake.is_suppressed() or events.is_automated() or events.is_quiet():
        return

    scope = DraftScope(project_id=subject.item.project_id, type_id=subject.item.type_id)
    verdict = await intake.validate_intake(session, subject.item.id, scope, required_only=True)
    if verdict.blocks:
        logger.info(
            "automations: refused %s in project %s — %d validation finding(s)",
            subject.item.id,
            subject.project.key,
            len(verdict.findings),
        )
        raise intake.ValidationBlocked(verdict)
