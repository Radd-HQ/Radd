"""The request-path half of intake validation (spec 119).

`validation.py` answers "what governs this draft and what did the checks say".
This is what a caller actually does with that: create inside a savepoint, ask,
and either let the savepoint stand or take it back.

**Auto-create on pass, one round trip.** The rejected alternative was a
pre-flight endpoint that validates and returns a signed receipt the real create
then presents. It needs two requests, a signature scheme, and a window in which
the thing that was validated and the thing that gets created can differ — for a
check that is cheap to simply run again. Creating first and rolling back is the
same work with none of the ceremony, and the row that was validated IS the row
that survives.

**Why the savepoint is safe.** `items.create_item` is pure DB: search, realtime,
webhooks and notifications are all outbox consumers reading committed rows, and
the `item.created` event is itself a row that rolls back with everything else.
Nothing outside the transaction can observe a draft that did not survive.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, RaddError
from radd.modules.auth.models import User
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEntity
from radd.modules.items.schemas import ItemCreate, ItemRead

from .validation import (
    DraftScope,
    IntakeVerdict,
    governing_graphs,
    run_graphs,
)
from .types import ValidationMode

logger = logging.getLogger(__name__)


class IntakeCommit(StrEnum):
    """What the caller wants done with the draft once the checks have spoken.

    Three, not a boolean, because "create it if it passes" and "create it
    regardless" and "tell me but create nothing" are three different asks and
    the middle one is what a "create anyway" button means.
    """

    #: Keep it when the checks pass, roll it back when they do not. The default,
    #: and the one that makes an ordinary Submit a single round trip.
    PASS = "pass"
    #: Keep it whatever they say — the advisory "create anyway". Refused with a
    #: 409 when any governing binding is REQUIRED: a mode the admin chose is not
    #: something a request parameter gets to override.
    ALWAYS = "always"
    #: Create nothing. A pure pre-flight, for a caller that wants the findings
    #: before it commits to anything.
    NEVER = "never"


class ValidationBlocked(RaddError):
    """Intake validation refused a creation (-> 422).

    The THIRD 422 vocabulary alongside the field registry's `{detail, errors}`
    and the workflow guards' `{detail, errors, from_state, to_state}`. It carries
    `findings` rather than `errors` deliberately: an error names a value the API
    could not accept, a finding names something a person should go and fix, and
    the client renders them differently — one against a control, one in a panel.
    """

    def __init__(self, verdict: IntakeVerdict):
        self.verdict = verdict
        self.findings = list(verdict.findings)
        super().__init__("; ".join(finding.message for finding in verdict.findings))


@dataclass(frozen=True)
class IntakeOutcome:
    """What `validate_and_create` did. `created` is None when nothing survived —
    which is not the same as a failure, since `NEVER` asks for exactly that."""

    verdict: IntakeVerdict
    created: ItemRead | None = None


# --- re-entrance ---------------------------------------------------------------

_suppressed: ContextVar[bool] = ContextVar("radd_intake_validation_suppressed", default=False)


def is_suppressed() -> bool:
    return _suppressed.get()


@contextmanager
def suppressed() -> Iterator[None]:
    """Turn the `item.creating` hook off for the duration — THE PUBLIC SEAM for
    a caller whose writes are not intake.

    Two kinds of caller need it, and they are the same need:

    * **the savepoint flow's own inner create**, which goes through the SAME
      `items.create_item` every other caller uses — that is the whole point of
      it — so without this the hook would run the required checks a second time
      on the same draft in the same transaction;
    * **machines and history** — an importer replaying old issues, the mail
      poller, the Alertmanager receiver. Each of them creates an item, and none
      of them is a person submitting a request through a form. `events.quiet()`
      covers the importer only when the plan asked for quiet, and it is the
      wrong lever for the other two: they WANT their notifications.

    A ContextVar rather than a parameter for the reason `events.quiet` is one:
    the dispatch happens deep inside a service that must stay ignorant of who is
    calling it. Reached by other modules deferred and feature-detected, so an
    instance without `automations` behaves identically.
    """
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


# --- the two entry points ------------------------------------------------------


async def validate_intake(
    session: AsyncSession,
    item_id: uuid.UUID,
    scope: DraftScope,
    *,
    required_only: bool = False,
) -> IntakeVerdict:
    """Run every governing graph over an EXISTING row and report what they found.

    Takes an item id rather than a draft because the checks are the same checks
    an automation runs, and those read rows.
    """
    graphs = await governing_graphs(session, scope, required_only=required_only)
    return await run_graphs(session, item_id, scope, graphs)


async def validate_and_create(
    session: AsyncSession,
    data: ItemCreate,
    actor: User,
    *,
    form_id: uuid.UUID | None = None,
    commit: IntakeCommit = IntakeCommit.PASS,
) -> IntakeOutcome:
    """Create inside a savepoint, validate the real row, keep it or take it back.

    The verdict comes back either way, so a caller that was refused can show WHY
    and a caller that succeeded can still show advice it chose to proceed past.
    """
    savepoint = await session.begin_nested()
    try:
        with suppressed():
            created = await items_service.create_item(session, data, actor=actor)
        item = await items_service.require_item(session, created.id)
        scope = DraftScope(
            project_id=item.project_id, type_id=item.type_id, form_id=form_id
        )
        verdict = await validate_intake(session, item.id, scope)
    except BaseException:
        # An ordinary refusal from create_item (authz, field validation) must
        # leave the outer transaction usable: the savepoint is rolled back and
        # the error travels on to its own handler.
        await savepoint.rollback()
        raise

    if commit is IntakeCommit.ALWAYS and verdict.blocks:
        # `create anyway` is an advisory affordance. A required binding is the
        # admin's decision, and a request parameter does not get to overrule it
        # — so this is a 409 about the request, not a 422 about the draft.
        await savepoint.rollback()
        raise ConflictError(
            ItemEntity.ITEM,
            reason=(
                "this intake is validated in required mode — the problems below must be "
                "fixed before it can be created"
            ),
        )

    keep = commit is IntakeCommit.ALWAYS or (commit is IntakeCommit.PASS and verdict.passed)
    if keep:
        await savepoint.commit()
        return IntakeOutcome(verdict=verdict, created=created)
    await savepoint.rollback()
    return IntakeOutcome(verdict=verdict, created=None)


async def create_or_refuse(
    session: AsyncSession,
    data: ItemCreate,
    actor: User,
    *,
    form_id: uuid.UUID | None = None,
    commit: IntakeCommit = IntakeCommit.PASS,
) -> ItemRead:
    """`validate_and_create` for callers whose contract is "an item or an error"
    — the form submit paths, which have always answered with the created item.
    """
    outcome = await validate_and_create(session, data, actor, form_id=form_id, commit=commit)
    if outcome.created is None:
        raise ValidationBlocked(outcome.verdict)
    return outcome.created


async def context_for(session: AsyncSession, scope: DraftScope) -> tuple[bool, ValidationMode | None]:
    """`(governed, mode)` for a draft that does not exist yet — what the SPA asks
    before it decides whether its button says Submit or Validate.

    Resolution only; no graph is walked, because the answer is a property of the
    bindings and running the checks against a draft nobody has written yet would
    be answering a different question.
    """
    from .validation import strictest

    graphs = await governing_graphs(session, scope)
    if not graphs:
        return False, None
    return True, strictest([graph.mode for graph in graphs])
