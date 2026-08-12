"""Intake validation: the same graph engine, run as a question instead of a job.

Spec 119. A `validate` trigger binds a graph to what someone is about to create —
a form, an issue type, a project — and the graph is walked SYNCHRONOUSLY against
a real row created inside a savepoint. Nothing it contains applies: the walk runs
with `apply=False`, and the only thing it produces is a list of `Finding`s.

Two halves live here, and they are deliberately apart:

* **Parsing** a validate trigger's params (`targets`, `mode`) — pure, so the
  write path and the read path cannot disagree about what a stored node means.
* **Resolving and running** the graphs that govern one draft.

Why a real row rather than a draft representation: a packet carries entity IDs
(`graph.Packet`), and every node downstream — `filter.slq` compiling SLQ against
one item, the AI context builder reading an `ItemRead` — is written against rows
that exist. Teaching all of that to speak a second, draft-shaped dialect of an
item is the version where the check that passes at intake is not the check that
would have run afterwards. A savepoint gives the row for the length of one
question and takes it back, and `items.create_item` is pure-DB (search, realtime
and webhooks are outbox consumers), so nothing outside the transaction ever
learns the draft existed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.items.models import WorkItem

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
        """Whether these findings must refuse the creation."""
        return bool(self.findings) and self.mode is ValidationMode.REQUIRED


# --- parsing a validate trigger's params -------------------------------------


def parse_targets(params: dict) -> list[ValidationTarget]:
    """`params["targets"]` as typed rows, dropping anything unreadable.

    Loose by construction, and the same choice card layouts made: a target whose
    id no longer parses is a binding that stops matching, not a graph that
    refuses to load. The WRITE path is where a malformed target is refused
    (`service._check_validate_trigger`), and it is strict there — which is what
    makes this parser's leniency a degradation rather than a hole.
    """
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


def parse_mode(params: dict) -> ValidationMode:
    """The binding's mode; ADVISORY for anything unrecognised.

    Advisory is the safe default in both directions: a graph whose mode was
    mistyped shows its findings instead of silently blocking every submission,
    and an admin who meant `required` sees advice rather than nothing at all.
    """
    try:
        return ValidationMode(str(params.get("mode")))
    except ValueError:
        return ValidationMode.ADVISORY


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
    targets, deduplicated per (automation, trigger node).

    Deduplicated because one trigger may name the project AND the form the draft
    came through; without it the graph would run twice and every finding would
    arrive in pairs. The dedupe keeps the STRICTEST mode among the matched rows,
    which is the same rule the verdict uses one level up.
    """
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
    is none for a manual run or a schedule. The scope rides in the payload so a
    `gate.event` on `payload.form_id` can still say something useful."""
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
    """Walk every governing graph over the draft and concatenate what they found.

    Every graph runs even after one has already produced findings. Stopping at
    the first would make the list of problems depend on the order automations
    happen to be positioned in, and someone fixing one issue would be told about
    the next only on their second attempt.
    """
    if not graphs:
        return IntakeVerdict(governed=False)

    # Deferred: `engine` imports this module's siblings, and validation is
    # reached from the request path rather than from the consumer loop.
    from . import engine

    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    initial = Packet.of(validate_facts(item_id, scope), item=(item_id,))
    collected = _Collected()
    for governing in graphs:
        collected.modes.append(governing.mode)
        report = await engine.run_graph(
            session,
            governing.automation,
            initial,
            system_user,
            # THE INVARIANT of a validation walk: an action node never applies.
            # It is `walk`'s existing dry-run switch, not a second walker —
            # which is what makes "what validation saw" and "what a run would
            # do" the same code with one thing turned off.
            apply=False,
            start_node_id=governing.node_id,
        )
        if report is None:
            logger.warning(
                "automations: validation graph %s would not load; treating it as silent",
                governing.automation.name,
            )
            continue
        collected.findings.extend(report.findings)

    if len(collected.findings) > MAX_INTAKE_FINDINGS:
        dropped = len(collected.findings) - MAX_INTAKE_FINDINGS
        collected.findings = collected.findings[:MAX_INTAKE_FINDINGS]
        collected.findings.append(
            Finding(node_id="", message=f"…and {dropped} more problem(s) not shown.")
        )
    return IntakeVerdict(
        mode=strictest(collected.modes),
        findings=tuple(collected.findings),
        governed=True,
    )


async def scope_of(session: AsyncSession, item: WorkItem, form_id: uuid.UUID | None) -> DraftScope:
    """The draft's scope, read off the row that was just created."""
    return DraftScope(project_id=item.project_id, type_id=item.type_id, form_id=form_id)
