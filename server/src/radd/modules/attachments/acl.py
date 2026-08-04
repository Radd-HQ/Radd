"""Per-attachment read ACL (spec 102), on the spec-92 generic access framework.

One rule: an attachment with NO grant rows is open to everyone who can read its
parent (pre-102 behavior); ANY grant row restricts it to matching subjects
(user/team/role), with the uploader and parent-write holders always passing
(`has_manage`). Registering the ResourceSpec buys the generic /grants API and
the <AccessGrantsEditor> UI with no new endpoints.

Grants are written unscoped (global rows) — an attachment already lives inside
one parent, so per-project scoping adds nothing.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.access import registry as access_registry
from radd.modules.access import resolution
from radd.modules.access import service as access_service
from radd.modules.access.types import Access, GrantSubject
from radd.modules.auth.models import User

from . import parents
from .models import Attachment

ATTACHMENT_RESOURCE = "attachment"


async def _can_manage(
    session: AsyncSession, actor: User, resource_id: str, project_id: uuid.UUID | None
) -> bool:
    """Who may edit an attachment's grants: its uploader, or anyone who could
    write the parent (mirrors the delete rule)."""
    from . import service  # deferred: service imports nothing from here, but keep it lazy

    try:
        attachment = await service.get_attachment(session, uuid.UUID(resource_id))
    except (ValueError, NotFoundError):
        return False
    if attachment.created_by == actor.id:
        return True
    binding = parents.binding_for(attachment.entity_type)
    try:
        await binding.require_write(session, actor, attachment.entity_id)
    except (ForbiddenError, NotFoundError):
        return False
    return True


async def _attachment_labels(session: AsyncSession, resource_ids) -> dict[str, str]:
    """Inspector labels (RADD-809): attachment id -> filename."""
    from sqlalchemy import select

    ids = []
    for raw in resource_ids:
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not ids:
        return {}
    rows = await session.execute(
        select(Attachment.id, Attachment.filename).where(Attachment.id.in_(ids))
    )
    return {str(attachment_id): filename for attachment_id, filename in rows.all()}


_SPEC = access_registry.ResourceSpec(
    resource_type=ATTACHMENT_RESOURCE,
    can_manage=_can_manage,
    accesses=(Access.READ.value,),
    default_open=True,
    hierarchical=False,
    subjects=(GrantSubject.USER, GrantSubject.TEAM, GrantSubject.ROLE),
    project_scoped=False,
    label="Attachment",
    label_for=_attachment_labels,
)
access_registry.register_resource(_SPEC)


async def _base_subjects(
    session: AsyncSession, user: User, attachment: Attachment
) -> tuple[frozenset[uuid.UUID], frozenset[uuid.UUID], bool]:
    """(role_ids, team_ids, parent_writable) for one parent — shared across a
    listing; `has_manage` is finished per attachment (the uploader varies)."""
    from radd.modules.auth import authz
    from radd.modules.projects import service as projects_service
    from radd.modules.teams import service as teams_service

    binding = parents.binding_for(attachment.entity_type)
    project_id = await binding.project_id_of(session, attachment.entity_id)
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        subjects = await authz.subjects_for(session, user, project)
        role_ids, team_ids = subjects.role_ids, subjects.team_ids
    else:
        # No project (wiki parents): role-subject grants can't resolve a scope,
        # so user/team subjects carry the restriction.
        role_ids = frozenset()
        team_ids = frozenset(await teams_service.user_team_ids(session, user.id))
    try:
        await binding.require_write(session, user, attachment.entity_id)
        parent_writable = True
    except (ForbiddenError, NotFoundError):
        parent_writable = False
    return role_ids, team_ids, parent_writable


def _context(
    user: User,
    attachment: Attachment,
    role_ids: frozenset[uuid.UUID],
    team_ids: frozenset[uuid.UUID],
    parent_writable: bool,
) -> resolution.SubjectContext:
    return resolution.SubjectContext(
        user_id=user.id,
        role_ids=role_ids,
        team_ids=team_ids,
        # Uploaders and parent-writers always pass their own files' gates.
        has_manage=parent_writable or attachment.created_by == user.id,
    )


async def attachment_readable(
    session: AsyncSession, user: User, attachment: Attachment
) -> bool:
    """Parent readable AND (no grants | matching grant | uploader/parent-writer)."""
    binding = parents.binding_for(attachment.entity_type)
    try:
        await binding.require_read(session, user, attachment.entity_id)
    except (ForbiddenError, NotFoundError):
        return False
    grants = await access_service.list_for_resource(
        session, ATTACHMENT_RESOURCE, str(attachment.id)
    )
    if not grants:
        return True
    role_ids, team_ids, parent_writable = await _base_subjects(session, user, attachment)
    ctx = _context(user, attachment, role_ids, team_ids, parent_writable)
    return resolution.has_access(grants, ctx, Access.READ.value, None, _SPEC)


async def readable_map(
    session: AsyncSession, user: User, attachments: list[Attachment]
) -> dict[uuid.UUID, tuple[bool, bool]]:
    """{attachment_id: (readable, restricted)} for one parent's listing — the
    caller has already passed the parent read gate, so only grants are checked
    here (batched, no N+1). `restricted` drives the lock badge."""
    grants_by_id = await access_service.grants_for_resources(
        session, ATTACHMENT_RESOURCE, [a.id for a in attachments]
    )
    out: dict[uuid.UUID, tuple[bool, bool]] = {}
    base: tuple[frozenset[uuid.UUID], frozenset[uuid.UUID], bool] | None = None
    for attachment in attachments:
        grants = grants_by_id.get(str(attachment.id), [])
        if not grants:
            out[attachment.id] = (True, False)
            continue
        if base is None:  # one parent per listing -> resolve subjects once
            base = await _base_subjects(session, user, attachment)
        ctx = _context(user, attachment, *base)
        out[attachment.id] = (
            resolution.has_access(grants, ctx, Access.READ.value, None, _SPEC),
            True,
        )
    return out
