"""Requester portal (spec 73). A form is eligible when ENABLED and (allow_public
or shared with the actor or their teams); the share IS the grant, so submits run
as the SYSTEM actor with `reporter_id=actor.id`. Ineligible is one 404."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.fields import service as fields_service
from radd.modules.teams import service as teams_service
from radd.modules.projects import service as projects_service
from radd.modules.items.enums import ItemOrigin

from . import service
from .models import Form, FormShare
from .schemas import (
    FormSubmit,
    PortalFormCard,
    PublicFormField,
    PublicFormRead,
    PortalFormRead,
    PortalGroup,
    PortalProjectRef,
    PortalTeamOption,
    PublicSubmitResult,
)
from .types import FormEntity


async def trimmed_read(session: AsyncSession, form: Form) -> PublicFormRead:
    """The trimmed render payload with field definitions inlined — a portal visitor
    may not read the field registry."""
    project = await projects_service.get_project(session, form.project_id)
    definitions = {
        definition.key: definition
        for definition in await fields_service.definitions_for_project(session, project)
    }
    fields: list[PublicFormField] = []
    for form_field in form.fields:
        definition = definitions.get(form_field["field_key"])
        if definition is None:
            continue  # dropped from the registry since the form was built
        fields.append(
            PublicFormField(
                field_key=definition.key,
                label=form_field.get("label_override") or definition.name,
                help=form_field.get("help"),
                required=bool(form_field.get("required")),
                type=definition.type,
                options=definition.options,
                display=definition.display,
                default_value=definition.default_value,
            )
        )
    return PublicFormRead(
        name=form.name,
        description=form.description,
        title_prompt=form.title_prompt,
        description_enabled=form.description_enabled,
        description_prompt=form.description_prompt,
        description_required=form.description_required,
        fields=fields,
    )


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
        shared = await session.scalar(
            _shared_form_ids(actor, team_ids).where(FormShare.form_id == form.id).limit(1)
        )
        if shared is not None:
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


async def nav_portal_visible(session: AsyncSession, actor: User) -> bool:
    """Is the requester portal worth offering (RADD-843, contributed as a
    NavFactSpec in RADD-892)? Eligibility for at least one form — the same
    computation `GET /portal/forms` runs, kept here so the nav answer and the
    page can never disagree."""
    return bool(await list_portal_forms(session, actor))


async def render_portal_form(
    session: AsyncSession, form_id: uuid.UUID, actor: User
) -> PortalFormRead:
    """Render payload for an ELIGIBLE actor: the trimmed form plus its id and project."""
    form = await _eligible_form(session, form_id, actor)
    project = await projects_service.get_project(session, form.project_id)
    base = await trimmed_read(session, form)
    return PortalFormRead(
        id=form.id,
        project=PortalProjectRef(id=project.id, key=project.key, name=project.name),
        teams=await _my_team_options(session, form, actor),
        # Spec 119 — the same resolution the authed submit page gets, which is
        # the only one that knows the form's effective TYPE (`service.
        # effective_type_id`): the submitter never picks one, so a type-targeted
        # binding is invisible from the client until the 422 lands.
        validation=await service.validation_context(session, form),
        **base.model_dump(),
    )


async def _my_team_options(
    session: AsyncSession, form: Form, actor: User
) -> list[PortalTeamOption]:
    """The submitter's OWN teams only (RADD-798) — offering every team would let
    anyone drop work into a stranger's queue. Re-checked at submit."""
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
    """Validate a submitted team choice server-side (UI is not enforcement):
    refused for a team the submitter is not in, and for ANY team on a form with
    no picker."""
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
    """Create as the SYSTEM actor with the visitor as reporter: the share is the grant."""
    # Deferred: automations loads after forms.
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    form = await _eligible_form(session, form_id, actor)
    # RADD-798: validate the team choice before anything is written.
    team_id = await _resolve_shared_team(session, form, actor, data.team_id)
    system = await auth.get_user(session, SYSTEM_ACTOR_ID)
    item = await service.submit_form(
        session, form.id, data, system, reporter_id=actor.id, team_id=team_id,
        origin=ItemOrigin.PORTAL,
    )
    # RADD-800 — the files were uploaded before the item existed; move the ones
    # this submission claims onto it now.
    from . import staging

    await staging.claim(session, actor, item.id, data.attachment_ids)
    return PublicSubmitResult(key=item.key, title=item.title)
