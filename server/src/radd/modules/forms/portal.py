"""Requester portal (spec 73): the intake-form directory for signed-in users.

Eligibility = the form is ENABLED and (allow_public OR a `form_shares` row
matches the actor directly or one of their teams). The share IS the grant —
exactly the public-form trust model, so submits run as the SYSTEM actor with
`reporter_id=actor.id` (a known user: no mail-contact/ack path). Managing the
share list lives in service.update_sharing (`form.manage`); everything here is
for eligible visitors, and an ineligible/unknown/disabled form is one 404 — a
form you can't use might as well not exist.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.teams import service as teams_service
from radd.modules.projects import service as projects_service

from . import public, service
from .models import Form, FormShare
from .schemas import (
    FormSubmit,
    PortalFormCard,
    PortalFormRead,
    PortalGroup,
    PortalProjectRef,
    PortalTeamOption,
    PublicSubmitResult,
)
from .types import FormEntity


def _shared_form_ids(actor: User, team_ids: set[uuid.UUID]):
    """Subquery: form ids a share row grants to the actor or their teams."""
    return select(FormShare.form_id).where(
        or_(FormShare.user_id == actor.id, FormShare.team_id.in_(team_ids))
    )


async def _eligible_form(session: AsyncSession, form_id: uuid.UUID, actor: User) -> Form:
    form = await session.get(Form, form_id)
    if form is not None and form.enabled:
        if form.allow_public:
            return form
        team_ids = await teams_service.user_team_ids(session, actor.id)
        share = await session.scalar(
            select(FormShare.id)
            .where(FormShare.form_id == form.id)
            .where(or_(FormShare.user_id == actor.id, FormShare.team_id.in_(team_ids)))
            .limit(1)
        )
        if share is not None:
            return form
    raise NotFoundError(FormEntity.FORM, form_id)


async def list_portal_forms(session: AsyncSession, actor: User) -> list[PortalGroup]:
    """The directory: enabled forms across ALL projects the actor may use,
    grouped by project. Listing is by ELIGIBILITY, not membership (spec 73) —
    trimmed cards only, no tokens and no field config."""
    team_ids = await teams_service.user_team_ids(session, actor.id)
    result = await session.execute(
        select(Form)
        .where(Form.enabled.is_(True))
        .where(or_(Form.allow_public.is_(True), Form.id.in_(_shared_form_ids(actor, team_ids))))
        .order_by(Form.name, Form.id)
    )
    by_project: dict[uuid.UUID, list[Form]] = {}
    for form in result.scalars():
        by_project.setdefault(form.project_id, []).append(form)
    groups: list[PortalGroup] = []
    for project_id, forms in by_project.items():
        project = await projects_service.get_project(session, project_id)
        groups.append(
            PortalGroup(
                project=PortalProjectRef(id=project.id, key=project.key, name=project.name),
                forms=[
                    PortalFormCard(id=form.id, name=form.name, description=form.description)
                    for form in forms
                ],
            )
        )
    groups.sort(key=lambda group: (group.project.name.lower(), group.project.key))
    return groups


async def render_portal_form(
    session: AsyncSession, form_id: uuid.UUID, actor: User
) -> PortalFormRead:
    """Render payload for an ELIGIBLE actor: the spec-62 public trimming (the
    visitor may not read the registry) plus the form id + project ref."""
    form = await _eligible_form(session, form_id, actor)
    project = await projects_service.get_project(session, form.project_id)
    base = await public.trimmed_read(session, form)
    return PortalFormRead(
        id=form.id,
        project=PortalProjectRef(id=project.id, key=project.key, name=project.name),
        teams=await _my_team_options(session, form, actor),
        **base.model_dump(),
    )


async def _my_team_options(
    session: AsyncSession, form: Form, actor: User
) -> list[PortalTeamOption]:
    """The teams THIS submitter may share with (RADD-798).

    Their own teams, never the full list: offering every team would let anyone
    drop a request into any team's queue, and this picker is the only thing
    between "share with my team" and "assign work to strangers". The server
    re-checks the choice at submit regardless — a list is a convenience, not a
    control.
    """
    if not form.team_picker_enabled:
        return []
    team_ids = await teams_service.user_team_ids(session, actor.id)
    if not team_ids:
        return []
    found = await teams_service.teams_by_ids(session, list(team_ids))
    return sorted(
        (PortalTeamOption(id=t.id, name=t.name) for t in found.values()),
        key=lambda t: t.name,
    )


async def _resolve_shared_team(
    session: AsyncSession, form: Form, actor: User, team_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Validate a submitted team choice. UI is not enforcement (RADD-798).

    Refuses a team the submitter does not belong to, and refuses ANY team when
    the form has no picker — otherwise a hand-made request could attach itself
    to a team's queue on a form whose author deliberately turned sharing off.
    """
    if team_id is None:
        return None
    if not form.team_picker_enabled:
        raise ConflictError(FormEntity.FORM, reason="this form does not offer team sharing")
    if team_id not in await teams_service.user_team_ids(session, actor.id):
        raise ConflictError(FormEntity.FORM, reason="you are not a member of that team")
    return team_id


async def submit_portal_form(
    session: AsyncSession, form_id: uuid.UUID, data: FormSubmit, actor: User
) -> PublicSubmitResult:
    """Create the item as the SYSTEM actor with the visitor as reporter — the
    sharee may hold no item.create anywhere; the share is the grant. Form
    required-overrides + registry validation apply (422), like the public path."""
    # Deferred: automations loads after forms in RADD_MODULES (public.py idiom).
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    form = await _eligible_form(session, form_id, actor)
    # RADD-798: validate the team choice HERE, before anything is written. The
    # client only offers the submitter's own teams; that is presentation, and a
    # hand-made request must meet the same rule.
    team_id = await _resolve_shared_team(session, form, actor, data.team_id)
    system = await auth.get_user(session, SYSTEM_ACTOR_ID)
    item = await service.submit_form(
        session, form.id, data, system, reporter_id=actor.id, team_id=team_id
    )
    # RADD-800 — the files were uploaded before the item existed; move the ones
    # this submission claims onto it now.
    from . import staging

    await staging.claim(session, actor, item.id, data.attachment_ids)
    return PublicSubmitResult(key=item.key, title=item.title)
