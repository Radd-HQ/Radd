"""Wire shapes for intake validation (spec 119).

Kept out of `schemas.py`, which is already 685 lines of the automation-builder's
own vocabulary. These describe the INTAKE surface — what a person submitting a
request sends and gets back — and the two audiences share nothing.
"""

import uuid

from pydantic import BaseModel

from radd.modules.items.schemas import ItemCreate, ItemRead

from .executor import Finding
from .intake import IntakeCommit
from .types import ValidationMode
from .validation import IntakeVerdict


class IntakeValidateRequest(ItemCreate):
    """`ItemCreate` plus what to do with the result.

    A SUBCLASS rather than `{item: {...}, commit: …}`, so the body of a validated
    create is the body of a plain create with one field added — a client that
    already builds `POST /items` payloads does not learn a second shape.
    """

    commit: IntakeCommit = IntakeCommit.PASS
    #: The form this came through, when it came through one. Only affects which
    #: bindings match; it is never stored on the item.
    form_id: uuid.UUID | None = None

    def as_item_create(self) -> ItemCreate:
        """The plain create payload, with the intake fields removed.

        Re-validated from `exclude_unset` rather than passed through, because
        `items.create_item` reads `model_fields_set` to tell "omitted" from
        "explicitly null" — and that distinction has to survive the trip.
        """
        return ItemCreate.model_validate(
            self.model_dump(exclude={"commit", "form_id"}, exclude_unset=True)
        )


class FindingRead(BaseModel):
    """One problem, addressed at a control when it can be.

    `field` is a builtin name (`title`, `description`, `assignee`, …) or
    `cf.<key>`, and empty when the finding is about the submission as a whole.
    """

    message: str
    field: str = ""
    #: Which check said it. Not shown to the submitter; it is what makes a
    #: finding traceable back to the node that produced it when someone asks
    #: "where is this message coming from".
    node_id: str = ""


class VerdictRead(BaseModel):
    #: Whether anything governs this draft at all — distinct from `passed`,
    #: which an ungoverned draft also satisfies.
    governed: bool
    #: The STRICTEST mode among the graphs governing this draft. For display:
    #: it says what kind of thing is watching, not what happened.
    mode: ValidationMode
    passed: bool
    #: Whether these findings REFUSE the creation — `verdict.blocks`, the same
    #: property the 409 on `commit: always` is decided by, so the client's
    #: "create anyway" affordance and the server's answer to it cannot disagree.
    #:
    #: It is not `mode == required`: a draft governed by a required graph and an
    #: advisory one, tripping only the advisory, is advised and not refused. A
    #: client computing the affordance from `mode` hid a button the server would
    #: have honoured; one computing it from `passed` offers a button the server
    #: refuses. This is the fact, and there is exactly one of it.
    blocking: bool
    findings: list[FindingRead]


class IntakeValidateResult(BaseModel):
    """`created` is null when nothing survived: the checks refused it, or the
    caller only asked."""

    verdict: VerdictRead
    created: ItemRead | None = None


class ValidationContextRead(BaseModel):
    governed: bool
    #: Null exactly when nothing governs — so a client cannot mistake "advisory"
    #: for "ungoverned" and offer a Validate button that has nothing to run.
    mode: ValidationMode | None = None


def finding_read(finding: Finding) -> FindingRead:
    return FindingRead(message=finding.message, field=finding.field, node_id=finding.node_id)


def verdict_read(verdict: IntakeVerdict) -> VerdictRead:
    return VerdictRead(
        governed=verdict.governed,
        mode=verdict.mode,
        passed=verdict.passed,
        blocking=verdict.blocks,
        findings=[finding_read(finding) for finding in verdict.findings],
    )
