"""The request-path half of intake validation (spec 119): create inside a
savepoint, validate the real row, keep it or roll it back — one round trip, and
the row validated is the row that survives. Safe because `items.create_item` is
pure DB; everything downstream is an outbox consumer of committed rows.
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
    """What to do with the draft once the checks have spoken."""

    PASS = "pass"  # keep it only when the checks pass (the ordinary Submit)
    #: Keep it regardless — the advisory "create anyway"; 409 where a check is required.
    ALWAYS = "always"
    NEVER = "never"  # create nothing: a pure pre-flight


class ValidationBlocked(RaddError):
    """Intake validation refused a creation (→ 422 with `findings`, see the handler)."""

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
    """Turn the `item.creating` hook off for the duration — the seam for writes
    that are not intake: the savepoint flow's own inner create (else the checks
    run twice), and machine/history writers (importer, mail poller,
    Alertmanager), which still want notifications, so `events.quiet()` is the
    wrong lever. A ContextVar because the dispatch happens deep inside items.
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
