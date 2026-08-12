"""The intake-validation API (spec 119), mounted under `/items`.

**Why an items-shaped URL from the automations module.** `POST /items/validate`
is a thing you do to an item; naming it `/automations/validate-item` would make
every caller learn which subsystem happens to implement the checks. The
dependency runs the other way (items must never import automations), so the
ROUTER lives here and the PATH lives there.

That is only safe because of how Starlette matches. It tries routes in
declaration order, and `items` mounts before `automations` — but a path that
matches with the wrong METHOD is a PARTIAL match, and a later FULL match wins.
`POST /items/validate` therefore reaches this handler past `GET|PATCH|DELETE
/items/{item_id}`, and there is no `POST /items/{item_id}` for it to hide
behind. The context read is three segments (`/items/validate/context`) for the
same reason in reverse: as a two-segment GET it would sit behind
`GET /items/{item_id}` and answer a 422 about parsing "validate" as a UUID —
RADD-761's exact failure. `tests/test_route_shadowing.py` asserts both over the
assembled app.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import intake
from .intake import IntakeCommit
from .intake_schemas import (
    IntakeValidateRequest,
    IntakeValidateResult,
    ValidationContextRead,
    verdict_read,
)
from .validation import DraftScope

router = APIRouter(prefix="/items", tags=["items"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/validate", response_model=IntakeValidateResult)
async def validate_item(
    data: IntakeValidateRequest, session: Session, user: CurrentUser
) -> IntakeValidateResult:
    """Validate a draft against whatever governs it, and create it if asked.

    `item.create` is enforced by `items.create_item` inside the savepoint — this
    endpoint deliberately adds no gate of its own, so what it accepts and what
    `POST /items` accepts cannot drift.
    """
    outcome = await intake.validate_and_create(
        session, data.as_item_create(), user, form_id=data.form_id, commit=data.commit
    )
    return IntakeValidateResult(created=outcome.created, verdict=verdict_read(outcome.verdict))


@router.get("/validate/context", response_model=ValidationContextRead)
async def validation_context(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID,
    type_id: Annotated[uuid.UUID | None, Query()] = None,
    form_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ValidationContextRead:
    """Whether anything validates a draft with this shape, and how hard.

    Gated on `item.create` in the project — the same atom that decides whether
    the caller could create the draft at all, so this reveals nothing to anyone
    who could not have found out by trying. Portal visitors never call it: their
    answer rides on the form's own render payload, which is authorized by the
    share rather than by an item atom.
    """
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_CREATE, project=project)
    governed, mode = await intake.context_for(
        session, DraftScope(project_id=project_id, type_id=type_id, form_id=form_id)
    )
    return ValidationContextRead(governed=governed, mode=mode)


__all__ = ["router", "IntakeCommit"]
