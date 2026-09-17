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

    Four skips, and each is a different way of not being intake:

    * **the savepoint flow's own inner create** — it validates the draft itself,
      one level up, with the advisory bindings included; running again here
      would duplicate every finding;
    * **`events.automated()`** — an item the ENGINE created. An automation's own
      output is not somebody submitting a request, and a required check that
      refused it would break the automation rather than teach anyone anything;
    * **`events.quiet()`** — an import. Historical rows are not intake, and
      validating them would refuse to import exactly the badly-filled-in issues
      the checks exist to stop being created TODAY. (The importer also asks for
      `intake.suppressed()` in its own right, because quiet is a plan option and
      "this is history" is not.)
    * **machine intake** — the mail poller and the Alertmanager receiver, each
      of which asks for `intake.suppressed()` around its create. Neither has a
      channel to answer through: the poller marks the message Seen, so a refusal
      would drop a customer's request with no issue and no bounce, and the
      receiver would answer Alertmanager with a 5xx it will retry forever. A
      check written for a person filling in a form cannot be answered by a
      monitoring system, and refusing it silently is the worst of the options.

    Only REQUIRED bindings run here. Advisory findings have nowhere to go on
    this path — there is no one to show them to and nothing they would change —
    so charging every API create for them would be a cost with no product.
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
