import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.access import resolution as access_res, service as access_service
from radd.modules.access.service import AccessGrant  # public re-export (RADD-887)
from radd.modules.access.registry import ResourceSpec, register_resource
from radd.modules.access.types import Access
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import openapi
from .models import FieldDefinition, FieldProject
from .schemas import FieldDefinitionCreate, FieldDefinitionUpdate
from .types import (
    BuiltinItemField,
    READ_RESTRICTABLE_BUILTINS,
    SELECT_TYPES,
    FieldEntity,
    FieldEvent,
    FieldType,
)
from .validation import FieldValidationError, check_field_value

# Field grants live in the generic access framework (spec 92): read/write flags,
# open until restricted, write implies read, scopeable to projects. `access.registry`
# routes the generic /grants API + the reusable GrantsEditor to us via this spec.
FIELD_RESOURCE = "field"
async def _field_labels(session: AsyncSession, resource_ids) -> dict[str, str]:
    """Inspector labels (RADD-809): field-definition id -> display name."""
    ids = []
    for raw in resource_ids:
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not ids:
        return {}
    rows = await session.execute(
        select(FieldDefinition.id, FieldDefinition.name).where(FieldDefinition.id.in_(ids))
    )
    return {str(field_id): name for field_id, name in rows.all()}


async def _builtin_labels(session: AsyncSession, resource_ids) -> dict[str, str]:
    return {raw: raw.replace("_", " ").capitalize() for raw in resource_ids}


_FIELD_SPEC = ResourceSpec(
    resource_type=FIELD_RESOURCE,
    can_manage=lambda session, actor, resource_id, project_id: _can_manage_field(
        session, actor, resource_id
    ),
    accesses=(Access.READ.value, Access.WRITE.value),
    default_open=True,
    implied_by={Access.READ.value: (Access.WRITE.value,)},  # a writer can see what they write
    label="Custom field",
    label_for=_field_labels,
)


async def _can_manage_field(session: AsyncSession, actor, resource_id: str) -> bool:
    """A field's grants are managed by whoever holds field.manage on the field's own
    scope (every project it's scoped to, or globally when global)."""
    from radd.modules.auth import authz  # deferred: authz loads before fields

    try:
        definition = await get_field(session, uuid.UUID(resource_id))
    except (ValueError, NotFoundError):
        return False
    scopes = definition.project_ids
    if not scopes:
        return authz.Permission.FIELD_MANAGE in await authz.effective_permissions(session, actor)
    for project_id in scopes:
        project = await projects_service.get_project(session, project_id)
        perms = await authz.effective_permissions(session, actor, project=project)
        if authz.Permission.FIELD_MANAGE not in perms:
            return False
    return True


# Builtin item fields (state/assignee/…) take the SAME grant model (spec 92): the
# rule row is a grant on resource_type="builtin_field", resource_id = the field name.
# Authority is per-scope: field.manage on the grant's project (or globally).
BUILTIN_RESOURCE = "builtin_field"
_READ_RESTRICTABLE_NAMES = frozenset(f.value for f in READ_RESTRICTABLE_BUILTINS)


async def _can_manage_builtin(
    session: AsyncSession, actor, resource_id: str, project_id: uuid.UUID | None
) -> bool:
    from radd.modules.auth import authz

    if project_id is None:
        return authz.Permission.FIELD_MANAGE in await authz.effective_permissions(session, actor)
    project = await projects_service.get_project(session, project_id)
    return authz.Permission.FIELD_MANAGE in await authz.effective_permissions(
        session, actor, project=project
    )


_BUILTIN_SPEC = ResourceSpec(
    resource_type=BUILTIN_RESOURCE,
    can_manage=_can_manage_builtin,
    accesses=(Access.READ.value, Access.WRITE.value),
    default_open=True,
    implied_by={Access.READ.value: (Access.WRITE.value,)},
    label="Builtin field",
    label_for=_builtin_labels,
)


async def create_field(
    session: AsyncSession, data: FieldDefinitionCreate, actor_id: uuid.UUID | None = None
) -> FieldDefinition:
    scope_ids = list(dict.fromkeys(data.project_ids))  # dedupe, preserving order
    for project_id in scope_ids:
        await projects_service.get_project(session, project_id)
    existing = await session.scalar(
        select(FieldDefinition.id).where(FieldDefinition.key == data.key)
    )
    if existing:
        from radd.exceptions import ConflictError

        raise ConflictError(FieldEntity.FIELD, data.key)

    definition = FieldDefinition(
        # Empty project_ids = global; otherwise scoped to those projects.
        project_links=[FieldProject(project_id=pid) for pid in scope_ids],
        key=data.key,
        name=data.name,
        type=data.type.value,
        required=data.required,
        options=data.options,
        indexed=data.indexed,
        ai_visible=data.ai_visible,
        source=data.source.value,
        display=data.display.value if data.display else None,
        default_value=data.default_value,  # validated against type/options in the schema
    )
    session.add(definition)
    await session.flush()
    await events.emit(
        session,
        event_type=FieldEvent.CREATED,
        entity_type=FieldEntity.FIELD,
        entity_id=definition.id,
        actor_id=actor_id,
        payload={"key": definition.key, "type": definition.type},
    )
    # Known simplification (docs/modules.md): refreshed in-txn; move to an event consumer later.
    await _refresh_cache(session)
    return definition


async def update_field(
    session: AsyncSession, field_id: uuid.UUID, data: FieldDefinitionUpdate, actor_id: uuid.UUID
) -> FieldDefinition:
    """Edit a field's presentation (spec 52) + scope (spec 90). Read/write grants are
    managed through the generic /grants API, not here."""
    definition = await get_field(session, field_id)
    before = await _field_audit_state(session, definition)
    if data.name is not None:
        definition.name = data.name
    if data.project_ids is not None:
        for project_id in data.project_ids:
            await projects_service.get_project(session, project_id)
        wanted = list(dict.fromkeys(data.project_ids))
        definition.project_links = [FieldProject(project_id=pid) for pid in wanted]
    if "display" in data.model_fields_set:
        definition.display = data.display.value if data.display else None
    if "default_value" in data.model_fields_set:
        if data.default_value is not None:
            problem = check_field_value(
                FieldType(definition.type), definition.options, data.default_value
            )
            if problem:
                raise FieldValidationError([f"default_value {problem}"])
        definition.default_value = data.default_value
    await session.flush()
    await events.emit(
        session,
        event_type=FieldEvent.UPDATED,
        entity_type=FieldEntity.FIELD,
        entity_id=definition.id,
        actor_id=actor_id,
        payload={"key": definition.key, "name": definition.name},
        changes=changes.diff(before, await _field_audit_state(session, definition)),
    )
    await _refresh_cache(session)
    return definition


async def _field_audit_state(session: AsyncSession, definition: FieldDefinition) -> dict:
    """What a field diff can mention (spec 123): scope as project KEYS."""
    keys = {p.id: p.key for p in await projects_service.list_projects(session)}
    return {
        "name": definition.name,
        "display": definition.display,
        "default_value": definition.default_value,
        "projects": sorted(
            keys.get(link.project_id, str(link.project_id)) for link in definition.project_links
        ),
    }


async def extend_options(
    session: AsyncSession,
    field_id: uuid.UUID,
    values: list[str],
    actor_id: uuid.UUID | None = None,
) -> list[str]:
    """ADD options to a select field, keeping every existing one. Returns what was
    actually added.

    Deliberately not part of `update_field`, which holds options immutable: the
    dangerous edits are REMOVING or RENAMING an option, because existing items
    already store that value and would silently become invalid. Adding one cannot
    invalidate anything, so it is safe to expose on its own — and an importer
    mapping into a curated select needs exactly this, or real values get dropped.
    """
    definition = await get_field(session, field_id)
    if FieldType(definition.type) not in SELECT_TYPES:
        raise FieldValidationError([f"{definition.key} is not a select field"])
    existing = list(definition.options or [])
    known = {v.casefold() for v in existing}
    added = [v for v in dict.fromkeys(values) if v and v.casefold() not in known]
    if not added:
        return []
    # A new list, not a mutation: JSONB columns only persist on reassignment.
    definition.options = [*existing, *added]
    await session.flush()
    await events.emit(
        session,
        event_type=FieldEvent.UPDATED,
        entity_type=FieldEntity.FIELD,
        entity_id=definition.id,
        actor_id=actor_id,
        payload={"key": definition.key, "name": definition.name, "options_added": added},
        changes=[{"field": "options", "added": added, "removed": []}],
    )
    return added


async def option_usage(session: AsyncSession, field_id: uuid.UUID, value: str) -> int:
    """How many items carry `value` for this field — so the UI can ask the
    removal question with the number in it (RADD-949)."""
    from radd.modules.items import service as items_service

    definition = await get_field(session, field_id)
    return await items_service.count_with_value(session, definition.key, value)


async def remove_option(
    session: AsyncSession,
    field_id: uuid.UUID,
    value: str,
    *,
    replace_with: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> int:
    """REMOVE an option from a select field, migrating the items that hold it.

    `extend_options` above is additive because "removing is dangerous" — items
    already store the value and would silently become invalid. That is an
    argument for making the caller SAY what happens to those items, not for
    refusing forever: a field otherwise accumulates every value anyone ever
    typed, and an importer's strays are permanent.

    The decision is forced by the field, never defaulted:

      * **multi_select** — no replacement exists to ask for. The value is dropped
        from each item's list, and a shorter list is still valid.
      * **single select, required** — `replace_with` must name a SURVIVING
        option. Clearing would leave items violating their own field, which is
        the invalid state this whole function exists to avoid.
      * **single select, optional** — `replace_with` may be None, which clears
        the value.

    The field's own `default_value` is migrated in the same transaction. A
    default pointing at a removed option is the same invalidity one level up,
    and it is the one nobody would think to check — it would seed the dead value
    onto every item created afterwards.

    Returns the number of items touched.
    """
    from radd.modules.items import service as items_service

    definition = await get_field(session, field_id)
    field_type = FieldType(definition.type)
    if field_type not in SELECT_TYPES:
        raise FieldValidationError([f"{definition.key} is not a select field"])
    existing = list(definition.options or [])
    if value not in existing:
        raise FieldValidationError([f"{definition.key} has no option '{value}'"])
    survivors = [option for option in existing if option != value]
    if not survivors:
        raise FieldValidationError(
            [f"{definition.key} would have no options left — delete the field instead"]
        )

    multi = field_type is FieldType.MULTI_SELECT
    if not multi:
        if replace_with is not None and replace_with not in survivors:
            # Catches the obvious mistake of naming the option being removed.
            raise FieldValidationError(
                [f"'{replace_with}' is not one of {definition.key}'s remaining options"]
            )
        if replace_with is None and definition.required:
            raise FieldValidationError(
                [f"{definition.key} is required — name an option to move its items to"]
            )

    if multi:
        touched = await items_service.drop_from_multi_select(session, definition.key, value)
    else:
        touched = await items_service.migrate_custom_field_value(
            session, definition.key, value, replace_with
        )

    if definition.default_value == value:
        definition.default_value = None if multi else replace_with
    elif multi and isinstance(definition.default_value, list):
        definition.default_value = [v for v in definition.default_value if v != value] or None
    # A new list, not a mutation: JSONB columns only persist on reassignment.
    definition.options = survivors
    await session.flush()
    await _refresh_cache(session)
    await events.emit(
        session,
        event_type=FieldEvent.UPDATED,
        entity_type=FieldEntity.FIELD,
        entity_id=definition.id,
        actor_id=actor_id,
        payload={
            "key": definition.key,
            "name": definition.name,
            "option_removed": value,
            "replaced_with": replace_with,
            "items_migrated": touched,
        },
        changes=[{"field": "options", "added": [], "removed": [value]}],
    )
    return touched


async def delete_field(
    session: AsyncSession, field_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    """Delete a custom-field definition. Its access grants go too (access.clear_resource,
    since grants have no FK to the polymorphic resource). Values already in
    `work_items.custom_fields` are keyed JSONB and left in place, unrendered."""
    definition = await get_field(session, field_id)
    await events.emit(
        session,
        event_type=FieldEvent.DELETED,
        entity_type=FieldEntity.FIELD,
        entity_id=definition.id,
        actor_id=actor_id,
        payload={"key": definition.key, "name": definition.name},
    )
    await access_service.clear_resource(session, FIELD_RESOURCE, str(definition.id))
    await session.delete(definition)
    await session.flush()
    await _refresh_cache(session)


async def get_field(session: AsyncSession, field_id: uuid.UUID) -> FieldDefinition:
    definition = await session.get(FieldDefinition, field_id)
    if definition is None:
        raise NotFoundError(FieldEntity.FIELD, field_id)
    return definition


async def list_fields(
    session: AsyncSession,
    *,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[FieldDefinition]:
    query = select(FieldDefinition).order_by(FieldDefinition.created_at)
    if q:
        query = query.where(
            FieldDefinition.name.ilike(ilike_term(q)) | FieldDefinition.key.ilike(ilike_term(q))
        )
    if limit is not None:
        query = query.offset(offset).limit(limit)
    return list((await session.execute(query)).scalars())


async def count_fields(session: AsyncSession, *, q: str | None = None) -> int:
    query = select(func.count()).select_from(FieldDefinition)
    if q:
        query = query.where(
            FieldDefinition.name.ilike(ilike_term(q)) | FieldDefinition.key.ilike(ilike_term(q))
        )
    return (await session.execute(query)).scalar_one()


async def definitions_for_project(session: AsyncSession, project: Project) -> list[FieldDefinition]:
    """Fields in scope for a project: the GLOBAL ones (no scope rows) plus those
    scoped to this project (spec 90 follow-up — a field may be scoped to several)."""
    scoped_to_project = select(FieldProject.field_id).where(
        FieldProject.project_id == project.id
    )
    query = select(FieldDefinition).where(
        FieldDefinition.id.not_in(select(FieldProject.field_id))
        | FieldDefinition.id.in_(scoped_to_project)
    )
    return list((await session.execute(query)).scalars())


async def restricted_field_ids(session: AsyncSession, *, ids: list[str] | None = None) -> set[str]:
    """Field ids (as strings) carrying any grant — used for the `restricted` read flag."""
    return await access_service.resource_ids_with_grants(session, FIELD_RESOURCE, ids=ids)


async def outbound_restricted_keys(
    session: AsyncSession,
) -> tuple[frozenset[str], frozenset[str]]:
    """(custom-field keys, builtin names) carrying ANY read-restricting grant,
    instance-wide — the fail-closed set for consumers that can hold no grant
    and no subject (RADD-1085): a webhook endpoint, a cross-project surface
    with no per-project subject resolution. Restriction is rare; a leak is not
    (the denied_slq_fields precedent)."""
    definitions = await list_fields(session)
    field_grants = await access_service.grants_for_resources(
        session, FIELD_RESOURCE, [str(d.id) for d in definitions]
    )
    custom = frozenset(
        d.key
        for d in definitions
        if any(g.access == Access.READ.value for g in field_grants.get(str(d.id), ()))
    )
    builtin_grants = await access_service.grants_for_resources(
        session, BUILTIN_RESOURCE, sorted(_READ_RESTRICTABLE_NAMES)
    )
    builtins = frozenset(
        name
        for name, grants in builtin_grants.items()
        if any(g.access == Access.READ.value for g in grants)
    )
    return custom, builtins


# --- field-level visibility (now the generic access framework, spec 92) -------


@dataclass(frozen=True)
class FieldAccessContext:
    """What the acting user brings to a field grant check. Carries the resolved
    per-project subjects (role_ids/team_ids), the user, the project, and the fields'
    grants (batch-loaded) so read/write resolve through the generic framework.
    role_ids/team_ids/has_manage stay flat for the builtin-field rules path."""

    role_ids: frozenset[uuid.UUID] = frozenset()
    team_ids: frozenset[uuid.UUID] = frozenset()
    group_ids: frozenset[uuid.UUID] = frozenset()  # transitive directory groups (RADD-830)
    has_manage: bool = False
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    grants_by_field: Mapping[str, Sequence[AccessGrant]] = field(default_factory=dict)
    # Builtin-field READ grants in the project's scope, keyed by field name (spec 92).
    builtin_grants: Mapping[str, Sequence[AccessGrant]] = field(default_factory=dict)

    def as_subject(self) -> access_res.SubjectContext:
        return access_res.SubjectContext(
            user_id=self.user_id,
            role_ids=self.role_ids,
            team_ids=self.team_ids,
            group_ids=self.group_ids,
            has_manage=self.has_manage,
        )


def _grants_for(definition: Any, ctx: FieldAccessContext) -> Sequence[AccessGrant]:
    return ctx.grants_by_field.get(str(definition.id), ())


# RADD-816 (F5.2): `has_manage` on the field contexts now means INSTANCE ADMIN
# — the operator who administers the grant system sees through it, a named
# resource-layer rule the inspector already explains with the `*` row. The old
# meaning (project.manage held) is GONE: a project manager is denied like
# anyone else unless a grant names them. The framework (`has_access`) never
# consults the flag; these short-circuits are the fields module's own.


def field_readable(definition: Any, ctx: FieldAccessContext) -> bool:
    if ctx.has_manage:
        return True
    return access_res.has_access(
        _grants_for(definition, ctx), ctx.as_subject(), Access.READ.value, ctx.project_id, _FIELD_SPEC
    )


def field_writable(definition: Any, ctx: FieldAccessContext) -> bool:
    if ctx.has_manage:
        return True
    return access_res.has_access(
        _grants_for(definition, ctx), ctx.as_subject(), Access.WRITE.value, ctx.project_id, _FIELD_SPEC
    )


def readable(
    definitions: Sequence[FieldDefinition], ctx: FieldAccessContext
) -> list[FieldDefinition]:
    return [d for d in definitions if field_readable(d, ctx)]


def readable_keys(definitions: Sequence[FieldDefinition], ctx: FieldAccessContext) -> set[str]:
    return {d.key for d in readable(definitions, ctx)}


def writable_check(
    definitions: Sequence[FieldDefinition],
    values: Mapping[str, Any],
    ctx: FieldAccessContext,
) -> None:
    """Raise ForbiddenError (-> 403) when `values` touches fields the actor may not write."""
    by_key = {d.key: d for d in definitions}
    denied = sorted(
        key for key in values if key in by_key and not field_writable(by_key[key], ctx)
    )
    if denied:
        raise ForbiddenError(f"no permission to write custom fields: {', '.join(denied)}")


# --- builtin item fields (spec 36 → spec 92, same access framework) ----------


def builtin_write_denied(
    touched: Sequence[str],
    grants_by_field: Mapping[str, Sequence[AccessGrant]],
    subject: access_res.SubjectContext,
    project_id: uuid.UUID | None,
) -> list[str]:
    """Which of the touched builtin fields the actor may NOT write (grants scoped)."""
    if subject.has_manage:  # instance admin (RADD-816) — administers the grants
        return []
    return sorted(
        name
        for name in touched
        if not access_res.has_access(
            grants_by_field.get(name, ()), subject, Access.WRITE.value, project_id, _BUILTIN_SPEC
        )
    )


def builtin_read_denied(
    grants_by_field: Mapping[str, Sequence[AccessGrant]],
    subject: access_res.SubjectContext,
    project_id: uuid.UUID | None,
) -> list[str]:
    """Which read-restrictable builtin fields to blank for the actor (grants scoped)."""
    if subject.has_manage:  # instance admin (RADD-816)
        return []
    return sorted(
        name
        for name, grants in grants_by_field.items()
        if not access_res.has_access(grants, subject, Access.READ.value, project_id, _BUILTIN_SPEC)
    )


async def build_field_ctx(
    session: AsyncSession,
    definitions: Sequence[FieldDefinition],
    project: Project,
    *,
    user_id: uuid.UUID,
    has_manage: bool,
    subjects_lookup,
) -> FieldAccessContext:
    """Assemble a FieldAccessContext for a project: batch-load the fields' grants and,
    only if any grant exists, the actor's subjects. `subjects_lookup` is an async
    callable returning (role_ids, team_ids, group_ids) — passed in so items owns
    the authz call."""
    grants_by_field = await access_service.grants_for_resources(
        session, FIELD_RESOURCE, [str(d.id) for d in definitions]
    )
    # Builtin read grants in the project's scope drive read-blanking (spec 92).
    builtin_grants = await access_service.grants_for_resources(
        session, BUILTIN_RESOURCE, sorted(_READ_RESTRICTABLE_NAMES)
    )
    if not any(grants_by_field.values()) and not any(builtin_grants.values()):
        return FieldAccessContext(has_manage=has_manage, project_id=project.id)
    role_ids, team_ids, group_ids = await subjects_lookup()
    return FieldAccessContext(
        role_ids=role_ids,
        team_ids=team_ids,
        group_ids=group_ids,
        has_manage=has_manage,
        user_id=user_id,
        project_id=project.id,
        grants_by_field=grants_by_field,
        builtin_grants=builtin_grants,
    )


async def readonly_field_keys(
    session: AsyncSession,
    project: Project,
    *,
    user_id: uuid.UUID,
    role_ids: frozenset[uuid.UUID],
    team_ids: frozenset[uuid.UUID],
    group_ids: frozenset[uuid.UUID],
    has_manage: bool,
) -> list[str]:
    """The builtin field NAMES + custom field KEYS the actor may NOT WRITE in this project,
    resolved through the generic access framework (spec 92). This is per-(actor, project) and
    item-INDEPENDENT (field grants are project/global-scoped, never per-item), so the SPA can
    disable exactly those editors up front instead of erroring on save. RADD-816 removed the
    manager bypass: a project manager is denied like anyone else unless a grant names them. Workflow-state transitions are
    handled separately (per-item) via /items/{id}/allowed-transitions."""
    subject = access_res.SubjectContext(
        user_id=user_id,
        role_ids=role_ids,
        team_ids=team_ids,
        group_ids=group_ids,
        has_manage=has_manage,
    )
    # Builtin fields: every name that can carry a write grant (denied returns only truly-restricted).
    builtin_names = sorted(f.value for f in BuiltinItemField)
    builtin_grants = await access_service.grants_for_resources(
        session, BUILTIN_RESOURCE, builtin_names
    )
    denied_builtin = builtin_write_denied(builtin_names, builtin_grants, subject, project.id)

    # Custom fields in this project's scope: readable but not writable.
    definitions = await definitions_for_project(session, project)

    async def _subjects() -> tuple[
        frozenset[uuid.UUID], frozenset[uuid.UUID], frozenset[uuid.UUID]
    ]:
        return role_ids, team_ids, group_ids

    ctx = await build_field_ctx(
        session,
        definitions,
        project,
        user_id=user_id,
        has_manage=has_manage,
        subjects_lookup=_subjects,
    )
    denied_custom = [
        d.key for d in definitions if field_readable(d, ctx) and not field_writable(d, ctx)
    ]
    return sorted([*denied_builtin, *denied_custom])


async def _refresh_cache(session: AsyncSession) -> None:
    definitions = await list_fields(session)
    restricted_ids = await restricted_field_ids(session)
    restricted_keys = {d.key for d in definitions if str(d.id) in restricted_ids}
    openapi.refresh(definitions, restricted_keys)


async def warm_schema_cache() -> None:
    from radd.db import SessionLocal

    async with SessionLocal() as session:
        await _refresh_cache(session)


register_resource(_FIELD_SPEC)
register_resource(_BUILTIN_SPEC)
