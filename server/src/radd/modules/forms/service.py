import secrets
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.cycles import service as cycles_service
from radd.modules.events import service as events
from radd.modules.fields import service as fields_service
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.items.schemas import ItemCreate, ItemRead
from radd.modules.releases import service as releases_service
from radd.modules.teams import service as teams_service
from radd.modules.workflow import service as workflow
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .models import Form, FormShare
from .schemas import (
    FormCreate,
    FormDefaults,
    FormField,
    FormRead,
    FormShareEntry,
    FormShareRead,
    FormSharingUpdate,
    FormSubmit,
    FormUpdate,
)
from .types import FormEntity, FormEvent
from .validation import FormValidationError, missing_required_keys


def _read(form: Form, shares: Sequence[FormShare] = ()) -> FormRead:
    read = FormRead.model_validate(form)
    read.shares = [FormShareRead.model_validate(share) for share in shares]
    return read


async def _form_shares(session: AsyncSession, form_id: uuid.UUID) -> list[FormShare]:
    result = await session.execute(
        select(FormShare)
        .where(FormShare.form_id == form_id)
        .order_by(FormShare.created_at, FormShare.id)
    )
    return list(result.scalars())


async def _shares_by_form(
    session: AsyncSession, form_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[FormShare]]:
    if not form_ids:
        return {}
    result = await session.execute(
        select(FormShare)
        .where(FormShare.form_id.in_(form_ids))
        .order_by(FormShare.created_at, FormShare.id)
    )
    grouped: dict[uuid.UUID, list[FormShare]] = {}
    for share in result.scalars():
        grouped.setdefault(share.form_id, []).append(share)
    return grouped


async def get_form(session: AsyncSession, form_id: uuid.UUID) -> Form:
    form = await session.get(Form, form_id)
    if form is None:
        raise NotFoundError(FormEntity.FORM, form_id)
    return form


# --- write-time validation ---


async def _validate_fields(
    session: AsyncSession, project: Project, form_fields: Sequence[FormField]
) -> None:
    """Every referenced field_key must live in the project's registry scope (409)."""
    if not form_fields:
        return
    definitions = await fields_service.definitions_for_project(session, project)
    known = {definition.key for definition in definitions}
    for form_field in form_fields:
        if form_field.field_key not in known:
            raise ConflictError(
                FormEntity.FORM,
                reason=f"unknown field '{form_field.field_key}' not in project {project.key} scope",
            )


async def _validate_defaults(
    session: AsyncSession, defaults: FormDefaults
) -> None:
    """Unknown state/label/cycle/release names are stored (resolved at submit); an
    unknown assignee is rejected here (409)."""
    if defaults.assignee_email:
        user = await auth.get_user_by_email(session, defaults.assignee_email)
        if user is None:
            raise ConflictError(
                FormEntity.FORM, reason=f"unknown assignee '{defaults.assignee_email}'"
            )


# --- CRUD ---


async def create_form(session: AsyncSession, data: FormCreate, actor: User) -> FormRead:
    project = await projects_service.get_project(session, data.project_id)
    await authz.require(session, actor, Permission.FORM_CREATE, project=project)
    await _validate_fields(session, project, data.fields)
    await _validate_defaults(session, data.defaults)
    form = Form(
        project_id=project.id,
        name=data.name,
        description=data.description,
        enabled=data.enabled,
        fields=[field.model_dump(mode="json") for field in data.fields],
        defaults=data.defaults.model_dump(mode="json"),
        title_prompt=data.title_prompt,
        description_enabled=data.description_enabled,
        description_prompt=data.description_prompt,
        description_required=data.description_required,
        team_picker_enabled=data.team_picker_enabled,
    )
    session.add(form)
    await session.flush()
    await _emit(session, FormEvent.CREATED, form, project, actor)
    return _read(form)


async def list_forms(
    session: AsyncSession, project_id: uuid.UUID, actor: User
) -> list[FormRead]:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, actor, Permission.FORM_MANAGE, project=project)
    result = await session.execute(
        select(Form).where(Form.project_id == project_id).order_by(Form.created_at)
    )
    forms = list(result.scalars())
    shares = await _shares_by_form(session, [form.id for form in forms])
    return [_read(form, shares.get(form.id, [])) for form in forms]


async def render_form(session: AsyncSession, form_id: uuid.UUID, actor: User) -> FormRead:
    """Fetch a form for a submitter to render — open to ITEM_CREATE on its project."""
    form = await get_form(session, form_id)
    project = await projects_service.get_project(session, form.project_id)
    await authz.require(session, actor, Permission.ITEM_CREATE, project=project)
    return _read(form)


async def update_form(
    session: AsyncSession, form_id: uuid.UUID, data: FormUpdate, actor: User
) -> FormRead:
    form = await get_form(session, form_id)
    project = await projects_service.get_project(session, form.project_id)
    await authz.require(session, actor, Permission.FORM_UPDATE, project=project)
    if data.fields is not None:
        await _validate_fields(session, project, data.fields)
        form.fields = [field.model_dump(mode="json") for field in data.fields]
    if data.defaults is not None:
        await _validate_defaults(session, data.defaults)
        form.defaults = data.defaults.model_dump(mode="json")
    if data.name is not None:
        form.name = data.name
    if data.description is not None:
        form.description = data.description
    if data.enabled is not None:
        form.enabled = data.enabled
    if data.title_prompt is not None:
        form.title_prompt = data.title_prompt
    if data.description_enabled is not None:
        form.description_enabled = data.description_enabled
    if data.description_prompt is not None:
        form.description_prompt = data.description_prompt
    if data.description_required is not None:
        form.description_required = data.description_required
    if data.team_picker_enabled is not None:
        form.team_picker_enabled = data.team_picker_enabled
    if data.allow_public is not None:
        # Spec 62: mint the token on FIRST enable only; disabling keeps it, so
        # re-enabling restores the same public link.
        form.allow_public = data.allow_public
        if data.allow_public and form.public_token is None:
            form.public_token = secrets.token_urlsafe(32)
    await session.flush()
    await _emit(session, FormEvent.UPDATED, form, project, actor)
    return _read(form, await _form_shares(session, form.id))


# --- portal sharing (spec 73) ---


async def _validate_share_subjects(
    session: AsyncSession, entries: Sequence[FormShareEntry]
) -> None:
    """Participants-module precedent, all 409: a subject may appear once; a user
    must exist and be active (any active user holds the global member floor —
    spec 86); a team must exist."""
    seen: set[tuple[str, uuid.UUID]] = set()
    for entry in entries:
        key = ("user", entry.user_id) if entry.user_id else ("team", entry.team_id)
        if key in seen:
            raise ConflictError(FormEntity.FORM, reason=f"duplicate share subject {key[1]}")
        seen.add(key)  # type: ignore[arg-type]
    user_ids = [entry.user_id for entry in entries if entry.user_id is not None]
    users = await auth.users_by_ids(session, user_ids)
    for user_id in user_ids:
        user = users.get(user_id)
        if user is None or not user.active:
            raise ConflictError(FormEntity.FORM, reason=f"unknown or inactive user {user_id}")
    team_ids = [entry.team_id for entry in entries if entry.team_id is not None]
    teams = await teams_service.teams_by_ids(session, team_ids)
    for team_id in team_ids:
        if teams.get(team_id) is None:
            raise ConflictError(FormEntity.FORM, reason=f"team {team_id} does not exist")


async def update_sharing(
    session: AsyncSession, form_id: uuid.UUID, data: FormSharingUpdate, actor: User
) -> FormRead:
    """Replace the form's FULL portal share list (spec 73): delete-then-insert,
    the views-sharing idiom. Presence-only grants — no levels."""
    form = await get_form(session, form_id)
    project = await projects_service.get_project(session, form.project_id)
    await authz.require(session, actor, Permission.FORM_MANAGE, project=project)
    await _validate_share_subjects(session, data.shares)
    await session.execute(delete(FormShare).where(FormShare.form_id == form.id))
    for entry in data.shares:
        session.add(FormShare(form_id=form.id, user_id=entry.user_id, team_id=entry.team_id))
    await session.flush()
    await _emit(
        session, FormEvent.UPDATED, form, project, actor,
        extra={"share_count": len(data.shares)},
    )
    return _read(form, await _form_shares(session, form.id))


async def delete_form(session: AsyncSession, form_id: uuid.UUID, actor: User) -> None:
    form = await get_form(session, form_id)
    project = await projects_service.get_project(session, form.project_id)
    await authz.require(session, actor, Permission.FORM_DELETE, project=project)
    await _emit(session, FormEvent.DELETED, form, project, actor)
    await session.delete(form)
    await session.flush()


# --- submit ---


async def _resolve_state_id(
    session: AsyncSession, project: Project, state_name: str | None
) -> uuid.UUID | None:
    """Map the default state name to an id; unknown -> None (item takes the default state)."""
    if not state_name:
        return None
    for state in await workflow.list_states(session, project.id):
        if state.name == state_name:
            return state.id
    return None


async def _resolve_assignee_id(
    session: AsyncSession, email: str | None
) -> uuid.UUID | None:
    if not email:
        return None
    user = await auth.get_user_by_email(session, email)
    return user.id if user else None


async def _resolve_cycle_id(
    session: AsyncSession, project: Project, cycle_name: str | None
) -> uuid.UUID | None:
    if not cycle_name:
        return None
    for cycle in await cycles_service.list_cycles(session):
        if cycle.name == cycle_name:
            return cycle.id
    return None


async def _resolve_release_id(
    session: AsyncSession, project: Project, version: str | None
) -> uuid.UUID | None:
    if not version:
        return None
    release = await releases_service.resolve_release(session, project.id, version)
    return release.id if release else None


# submit_form's reporter default: distinguishes "not overridden" (the acting user
# becomes reporter, the pre-62 behavior) from an explicit None (reporter stays NULL).
_REPORTER_UNSET = object()


async def submit_form(
    session: AsyncSession,
    form_id: uuid.UUID,
    data: FormSubmit,
    actor: User,
    *,
    reporter_id: object = _REPORTER_UNSET,
    team_id: uuid.UUID | None = None,
) -> ItemRead:
    """Validate the submission against the form's required overrides + the registry, then
    create a work item in the form's project with the defaults applied.

    ITEM_CREATE on the project is enforced by items.create_item. `reporter_id`
    (spec 62, the public path): pass a user id — or None to keep the reporter
    unset — instead of crediting the acting (SYSTEM) user."""
    form = await get_form(session, form_id)
    project = await projects_service.get_project(session, form.project_id)
    await authz.require(session, actor, Permission.ITEM_CREATE, project=project)
    if not form.enabled:
        raise ConflictError(FormEntity.FORM, reason=f"form '{form.name}' is disabled")

    # Form-level required overrides -> 422 naming the offending fields. The registry's
    # own type/unknown/required checks run inside create_item (validate_custom_fields).
    missing = missing_required_keys(form.fields, data.values)
    if missing:
        raise FormValidationError([f"{key}: required" for key in missing])

    # The description area follows the same required-override contract; a form
    # with the area disabled ignores any submitted description outright.
    description = data.description.strip() if form.description_enabled else ""
    if form.description_enabled and form.description_required and not description:
        raise FormValidationError(["description: required"])

    defaults = form.defaults
    # Only an explicit override lands in model_fields_set — an omitted reporter_id
    # keeps items.create_item's "the acting user raised it" default.
    reporter_override: dict[str, uuid.UUID | None] = (
        {} if reporter_id is _REPORTER_UNSET else {"reporter_id": reporter_id}  # type: ignore[dict-item]
    )
    item = ItemCreate(
        project_id=project.id,
        title=data.title,
        description=description,
        kind=ItemKind(defaults["kind"]) if defaults.get("kind") else ItemKind.ISSUE,
        priority=Priority(defaults["priority"]) if defaults.get("priority") else Priority.NORMAL,
        state_id=await _resolve_state_id(session, project, defaults.get("state_name")),
        assignee_id=await _resolve_assignee_id(session, defaults.get("assignee_email")),
        cycle_id=await _resolve_cycle_id(session, project, defaults.get("cycle_name")),
        release_id=await _resolve_release_id(session, project, defaults.get("release_version")),
        # The submitter's team choice wins over any form default — sharing is
        # theirs to decide (RADD-798); the form only decides whether to ask.
        team_id=team_id,
        labels=list(defaults.get("labels") or []),
        custom_fields=dict(data.values),
        **reporter_override,
    )
    return await items_service.create_item(session, item, actor=actor)


# --- events ---


async def _emit(
    session: AsyncSession,
    event_type: FormEvent,
    form: Form,
    project: Project,
    actor: User,
    extra: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "name": form.name,
        "project_id": str(form.project_id),
        "enabled": form.enabled,
    }
    if extra:
        payload.update(extra)
    await events.emit(
        session,
        event_type=event_type,
        entity_type=FormEntity.FORM,
        entity_id=form.id,
        actor_id=actor.id,
        payload=payload,
    )
