"""Attachments on a submission, staged before the item exists (RADD-800).

The submission editor took no files, and `FormDescriptionArea` said why: *"the
item doesn't exist yet, so there's nothing to attach to."* True when written;
spec 102 made it false by giving attachments polymorphic parents and a GC that
removes bytes.

## Stage, then repoint

An upload needs a parent NOW and the item only exists later, so uploads land on a
per-person STAGING AREA and are repointed onto the item at submit. Chosen over
"create the item first, then upload" (you could not attach before sending, and
closing the tab loses the file) and over inlining base64.

## Why the staging id is derived, not chosen

The obvious design is a client-minted draft id. It is also the one with a hole:
the attachment guards receive only `(session, user, entity_id)`, so a
client-chosen id gives them nothing to check the caller against, and anyone who
learned your id could read what you staged.

So the id is `uuid5(NAMESPACE, user.id)` — one staging area per person,
derivable by the server from the caller alone. The guard becomes a comparison,
which is the strongest check available at that seam and needs no table.

That leaves one problem: with a single area per person, submitting one form
would otherwise sweep up files staged in another tab. So the submission NAMES
the attachments it is claiming, and each is verified to be sitting on the
caller's own staging area before it moves. Multi-tab safe, and a stolen id is
worth nothing.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.attachments import parents, service as attachments_service
from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth.models import User

from .types import FormEntity, FormEvent

#: Fixed namespace for deriving a person's staging id. A constant, not a
#: setting: changing it would strand every file already staged.
_STAGING_NAMESPACE = uuid.UUID("5f0a5b6c-9a3e-4c1f-8b2d-7e6a1c4d9f30")


def staging_id_for(user: User) -> uuid.UUID:
    """This person's staging area — derived, so the server can always re-derive
    it from the caller and never has to trust an id it was handed."""
    return uuid.uuid5(_STAGING_NAMESPACE, str(user.id))


async def _require_own_staging(
    session: AsyncSession, user: User, entity_id: uuid.UUID
) -> None:
    """The whole access rule: it is yours, or it is not your business.

    No permission atom is consulted. A portal requester holds `attachment.create`
    nowhere (RADD-790), and the relationship is the grant here exactly as it is
    for the submit itself — but the relationship in question is "this is your own
    scratch space", which is narrower than anything an atom could express.
    """
    del session
    if entity_id != staging_id_for(user):
        raise ConflictError(FormEntity.FORM, reason="that is not your staging area")


async def _no_project(session: AsyncSession, entity_id: uuid.UUID) -> uuid.UUID | None:
    """A staged file belongs to no project yet — the form's project is known, but
    the routing decision is better made once, when the item is real."""
    del session, entity_id
    return None


parents.register_parent(
    parents.ParentBinding(
        entity_type=AttachmentParentType.FORM_SUBMISSION.value,
        require_read=_require_own_staging,
        require_write=_require_own_staging,
        require_admin=_require_own_staging,
        project_id_of=_no_project,
        # `sweep_abandoned` emits this per staging area, so the ORDINARY spec-102
        # cascade removes the rows and the bytes. A second cleanup path would
        # have been a second thing to get wrong.
        deleted_event=FormEvent.STAGING_DELETED.value,
    )
)


async def claim(
    session: AsyncSession, user: User, item_id: uuid.UUID, attachment_ids: list[uuid.UUID]
) -> int:
    """Move the named staged files onto the item that was just created.

    Each is verified to be on the CALLER's staging area first. That check is the
    security of this feature: without it, naming somebody else's attachment id
    would drag their file onto your issue.

    Silently ignores ids that do not match rather than failing the submission —
    a request should not be lost because a file was swept or already claimed.
    """
    if not attachment_ids:
        return 0
    # The from-parent filter inside `repoint` is the ownership check described
    # above: an id not sitting on the caller's own staging area does not move.
    return await attachments_service.repoint(
        session,
        attachment_ids,
        from_entity_type=AttachmentParentType.FORM_SUBMISSION.value,
        from_entity_id=staging_id_for(user),
        to_entity_type=AttachmentParentType.ITEM.value,
        to_entity_id=item_id,
    )


async def sweep_abandoned(
    session: AsyncSession, older_than_days: int = 7
) -> list[uuid.UUID]:
    """Staging areas nobody came back to — emit `form.staging.deleted` for each
    and the ordinary spec-102 cascade removes the rows AND the bytes.

    Every form somebody opened, attached a screenshot to and then closed leaves
    bytes behind. A staging area has no natural delete to hang that off, so the
    trigger is AGE instead — but the EVENT is the same shape every other parent
    emits, which is why this needs no cleanup code of its own.

    Whole areas, not individual files: the unit the cascade understands is a
    parent. An area whose NEWEST file is still recent is left alone, so somebody
    mid-submission never loses the screenshot they just pasted. Someone who
    stages something every week simply keeps their area, which is correct — they
    are using it.

    A week is deliberately generous. Reclaiming a file somebody is still looking
    at is a worse failure than storing it a little longer.
    """
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=older_than_days)
    rows = await attachments_service.newest_per_parent(
        session, AttachmentParentType.FORM_SUBMISSION.value
    )
    return [area_id for area_id, newest in rows if newest < cutoff]
