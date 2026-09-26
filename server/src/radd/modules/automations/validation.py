"""Intake validation (spec 119): the graph engine run as a question. A
`validate` trigger binds a graph to a form, issue type or project; the graph is
walked synchronously over a real row created in a savepoint, `apply=False`,
producing only `Finding`s. A real row, not a draft shape, because every node
(SLQ filters, AI context) reads rows — a second draft dialect would make the
check at intake differ from the one that runs afterwards.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from time import monotonic

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import RaddError
from radd.modules.auth.models import User

from . import conditions
from .executor import Finding
from .graph import Packet
from .models import Automation, ValidationBinding
from .types import (
    MAX_INTAKE_FINDINGS,
    MAX_VALIDATION_TARGETS,
    SYSTEM_ACTOR_EMAIL,
    SYSTEM_ACTOR_ID,
    SYSTEM_ACTOR_NAME,
    VALIDATION_MODE_RANK,
    AutomationTrigger,
    ValidationMode,
    ValidationTargetKind,
)

logger = logging.getLogger(__name__)

#: The cheapest statement there is, used only to ask whether the connection can
#: still take one — see `_walk_one`.
_ALIVE = text("SELECT 1")


class ValidationUnavailable(RaddError):
    """The checks could not be completed (→ 503) — not the submitter's problem,
    and deliberately not a verdict: carrying on would invent one or 500 on the
    savepoint release."""


@dataclass(frozen=True)
class ValidationTarget:
    """One thing a validate trigger governs."""

    kind: ValidationTargetKind
    id: uuid.UUID


@dataclass(frozen=True)
class IntakeVerdict:
    """What every governing graph, together, said about one draft.

    `mode` is the STRICTEST any of them declared, so an advisory graph listed
    beside a required one cannot soften it. It is reported even when nothing was
    found, because the caller needs it to decide whether "create anyway" is an
    affordance to offer at all.
    """

    mode: ValidationMode = ValidationMode.ADVISORY
    findings: tuple[Finding, ...] = ()
    #: Whether ANY graph governs this draft. Distinct from `passed`: ungoverned
    #: and clean look the same in the findings list and are different facts.
    governed: bool = False

    @property
    def passed(self) -> bool:
        return not self.findings

    @property
    def blocks(self) -> bool:
        """Whether these findings refuse the creation — read off the findings, not
        the aggregated mode (an advisory-only trip under a required graph advises)."""
        return any(finding.mode == ValidationMode.REQUIRED.value for finding in self.findings)


# --- parsing a validate trigger's params -------------------------------------


def parse_targets(params: dict) -> list[ValidationTarget]:
    """`params["targets"]` as typed rows, dropping anything unreadable — lenient on
    read (a stale target stops matching); the WRITE path is strict
    (`service._check_validate_trigger`)."""
    found: list[ValidationTarget] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    for raw in params.get("targets") or []:
        if not isinstance(raw, dict):
            continue
        try:
            kind = ValidationTargetKind(str(raw.get("kind")))
            target_id = uuid.UUID(str(raw.get("id")))
        except (ValueError, TypeError):
            continue
        if (kind.value, target_id) in seen:
            continue
        seen.add((kind.value, target_id))
        found.append(ValidationTarget(kind=kind, id=target_id))
    return found[:MAX_VALIDATION_TARGETS]


def strictest(modes: list[ValidationMode]) -> ValidationMode:
    return max(modes, key=lambda mode: VALIDATION_MODE_RANK[mode], default=ValidationMode.ADVISORY)


# --- resolution ---------------------------------------------------------------


@dataclass(frozen=True)
class DraftScope:
    """What a draft IS, for the purpose of finding what governs it.

    All three axes at once, unioned rather than ranked: a project-wide rule and
    a form-specific one both apply to a submission through that form, and
    picking the "most specific" would silently drop the broader check that the
    admin wrote precisely so nothing could slip past it.
    """

    project_id: uuid.UUID
    type_id: uuid.UUID | None = None
    form_id: uuid.UUID | None = None

    def target_pairs(self) -> list[tuple[str, uuid.UUID]]:
        pairs = [(ValidationTargetKind.PROJECT.value, self.project_id)]
        if self.type_id is not None:
            pairs.append((ValidationTargetKind.ISSUE_TYPE.value, self.type_id))
        if self.form_id is not None:
            pairs.append((ValidationTargetKind.FORM.value, self.form_id))
        return pairs


@dataclass(frozen=True)
class GoverningGraph:
    automation: Automation
    node_id: str
    mode: ValidationMode


async def governing_graphs(
    session: AsyncSession, scope: DraftScope, *, required_only: bool = False
) -> list[GoverningGraph]:
    """Enabled automations whose validate trigger names any of this draft's
    targets, deduplicated per (automation, trigger) — a trigger naming both the
    project and the form would otherwise run twice."""
    pairs = scope.target_pairs()
    stmt = (
        select(Automation, ValidationBinding.node_id, ValidationBinding.mode)
        .join(ValidationBinding, ValidationBinding.automation_id == Automation.id)
        .where(
            Automation.enabled.is_(True),
            _target_clause(pairs),
        )
        .order_by(Automation.position, Automation.created_at)
    )
    if required_only:
        stmt = stmt.where(ValidationBinding.mode == ValidationMode.REQUIRED.value)

    merged: dict[tuple[uuid.UUID, str], GoverningGraph] = {}
    for automation, node_id, mode in (await session.execute(stmt)).all():
        key = (automation.id, node_id)
        parsed = ValidationMode(mode) if mode in set(ValidationMode) else ValidationMode.ADVISORY
        existing = merged.get(key)
        merged[key] = GoverningGraph(
            automation=automation,
            node_id=node_id,
            mode=strictest([parsed, existing.mode]) if existing else parsed,
        )
    return list(merged.values())


def _target_clause(pairs: list[tuple[str, uuid.UUID]]):
    from sqlalchemy import or_, tuple_

    return or_(
        *(
            tuple_(ValidationBinding.target_kind, ValidationBinding.target_id) == pair
            for pair in pairs
        )
    )


# --- running -------------------------------------------------------------------


def validate_facts(item_id: uuid.UUID, scope: DraftScope) -> conditions.EventFacts:
    """Stand-in facts for a validation run — there is no event, exactly as there
    is none for a manual run or a schedule. The scope rides in the payload so an
    "Event value is" gate on `form_id` can still say something useful."""
    return conditions.EventFacts(
        event_type=AutomationTrigger.VALIDATE.value,
        actor_id=str(SYSTEM_ACTOR_ID),
        actor_email=SYSTEM_ACTOR_EMAIL,
        actor_name=SYSTEM_ACTOR_NAME,
        payload={
            "item_id": str(item_id),
            "project_id": str(scope.project_id),
            "type_id": str(scope.type_id) if scope.type_id else None,
            "form_id": str(scope.form_id) if scope.form_id else None,
        },
    )


@dataclass
class _Collected:
    findings: list[Finding] = field(default_factory=list)
    modes: list[ValidationMode] = field(default_factory=list)


async def run_graphs(
    session: AsyncSession,
    item_id: uuid.UUID,
    scope: DraftScope,
    graphs: list[GoverningGraph],
) -> IntakeVerdict:
    """Walk every governing graph and concatenate their findings — all of them, so
    the list does not depend on the order automations are positioned in."""
    if not graphs:
        return IntakeVerdict(governed=False)

    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    initial = Packet.of(validate_facts(item_id, scope), item=(item_id,))
    collected = _Collected()
    # ONE deadline for the whole verdict: the walk holds the project's number lock.
    deadline = monotonic() + settings.intake_validation_budget_seconds
    for governing in graphs:
        collected.modes.append(governing.mode)
        report = await _walk_one(session, governing, initial, system_user, deadline)
        if report is None:
            logger.warning(
                "automations: validation graph %s would not load; treating it as silent",
                governing.automation.name,
            )
            continue
        # RADD-1329: each finding already says whether it blocks — the verdict
        # node that recorded it decided. Nothing is stamped from a graph mode.
        collected.findings.extend(report.findings)

    if len(collected.findings) > MAX_INTAKE_FINDINGS:
        dropped = collected.findings[MAX_INTAKE_FINDINGS:]
        collected.findings = collected.findings[:MAX_INTAKE_FINDINGS]
        collected.findings.append(
            Finding(
                node_id="",
                message=f"…and {len(dropped)} more problem(s) not shown.",
                # The overflow line inherits the strictest mode among what it
                # stands for, so truncation can never turn a blocking verdict
                # into a passing one.
                mode=strictest([ValidationMode(f.mode) for f in dropped]).value,
            )
        )
    return IntakeVerdict(
        mode=strictest(collected.modes),
        findings=tuple(collected.findings),
        governed=True,
    )


async def _walk_one(
    session: AsyncSession,
    governing: GoverningGraph,
    initial: Packet,
    system_user: User | None,
    deadline: float,
):
    """One governing graph, walked inside its OWN savepoint — not to undo writes
    (there are none) but to recover from a walk that aborted the transaction (a
    swallowed DBAPI error), which would otherwise 500 the whole create. The
    caller turns that into a 503."""
    # Deferred: `engine` imports this module's siblings, and validation is
    # reached from the request path rather than from the consumer loop.
    from . import engine

    nested = await session.begin_nested()
    try:
        report = await engine.run_graph(
            session,
            governing.automation,
            initial,
            system_user,
            apply=False,  # the invariant of a validation walk: nothing applies
            start_node_id=governing.node_id,
            deadline=deadline,
        )
        # Probe BEFORE releasing: ROLLBACK TO SAVEPOINT works in an aborted
        # transaction, RELEASE does not (a failed release needs a full rollback,
        # which would take the caller's whole transaction with it).
        await session.execute(_ALIVE)
    except Exception as exc:
        logger.exception(
            "automations: validation graph %s could not be run", governing.automation.name
        )
        await nested.rollback()
        raise ValidationUnavailable(
            "intake validation could not be completed — please try again"
        ) from exc
    await nested.commit()
    return report
