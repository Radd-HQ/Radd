import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
from radd.modules.access import resolution as access_res, service as access_service
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.projects.models import Project

from ..schemas import ItemRead

# --- field-level visibility (spec 07: per-role/team grants) ---


# A read-restricted builtin field (spec 50) is blanked out of the representation
# for non-granted principals. Only fields in READ_RESTRICTABLE_BUILTINS appear here
# (title/state/priority are never restrictable — see fields.types).
_BLANK_BUILTIN: dict[str, dict[str, Any]] = {
    "description": {"description": ""},
    "assignee": {"assignee": None},
    "reporter": {"reporter": None},
    "team": {"team": None},
    "parent": {"parent": None},
    "start_date": {"start_date": None},
    "target_date": {"target_date": None},
    "cycle": {"cycle": None},
    "release": {"release": None},
    "labels": {"labels": []},
    "flagged": {"flagged": False},
}


def _filter_read(
    read: ItemRead,
    definitions: Sequence[FieldDefinition],
    ctx: fields.FieldAccessContext,
    builtin_denied: Sequence[str] = (),
) -> ItemRead:
    """Drop custom_fields the actor may not see and blank read-restricted builtin
    fields (spec 07 + 50)."""
    allowed = fields.readable_keys(definitions, ctx)
    update: dict[str, Any] = {
        "custom_fields": {k: v for k, v in read.custom_fields.items() if k in allowed}
    }
    for field in builtin_denied:
        update.update(_BLANK_BUILTIN.get(field, {}))
    return read.model_copy(update=update)


async def _builtin_read_denied(
    session: AsyncSession, project: Project, ctx: fields.FieldAccessContext
) -> list[str]:
    """Builtin fields this actor may not read on the project (spec 50/92). The read
    grants + subjects were resolved into `ctx` by `_field_ctx` — cheap no-op for the
    common case (manage holder, or no read grants in scope)."""
    if ctx.has_manage or not any(ctx.builtin_grants.values()):
        return []
    return fields.builtin_read_denied(ctx.builtin_grants, ctx.as_subject(), ctx.project_id)


# ItemCreate/ItemUpdate attribute -> the BuiltinItemField it writes (spec 36 rules).
_BUILTIN_FIELD_MAP: dict[str, str] = {
    "title": "title",
    "description": "description",
    "state_id": "state",
    "priority": "priority",
    "assignee_id": "assignee",
    "reporter_id": "reporter",
    "team_id": "team",
    "labels": "labels",
    "parent_id": "parent",
    "start_date": "start_date",
    "target_date": "target_date",
    "cycle_id": "cycle",
    "release_id": "release",
    "flagged": "flagged",
}


async def _check_builtin_field_rules(
    session: AsyncSession,
    actor: User,
    project: Project,
    permissions: frozenset[Permission],
    fields_set: frozenset[str] | set[str],
) -> None:
    """Spec 36: builtin fields default write-open, but a rule row restricts a
    field to its role/team subjects (project.manage always passes). 403 names
    the denied fields, mirroring the custom-field grant message."""
    touched = {_BUILTIN_FIELD_MAP[key] for key in fields_set if key in _BUILTIN_FIELD_MAP}
    if not touched:
        return
    grants = await access_service.grants_for_resources(
        session, fields.BUILTIN_RESOURCE, sorted(touched)
    )
    if not any(grants.values()):
        return
    subjects = await authz.subjects_for(session, actor, project)
    subject = access_res.SubjectContext(
        user_id=actor.id,
        role_ids=subjects.role_ids,
        team_ids=subjects.team_ids,
        has_manage=Permission.PROJECT_MANAGE in permissions,
    )
    denied = fields.builtin_write_denied(sorted(touched), grants, subject, project.id)
    if denied:
        raise ForbiddenError("no permission to write fields: " + ", ".join(denied))


async def _field_ctx(
    session: AsyncSession,
    actor: User,
    project: Project,
    permissions: frozenset[Permission],
    definitions: Sequence[FieldDefinition],
) -> fields.FieldAccessContext:
    """The actor's field-grant context (spec 92): the fields' access grants + the
    actor's per-project subjects. Batch-loads grants and skips the subject lookup
    when no field in the project carries any grant (the common case)."""
    has_manage = Permission.PROJECT_MANAGE in permissions

    async def _subjects() -> tuple[frozenset[uuid.UUID], frozenset[uuid.UUID]]:
        subjects = await authz.subjects_for(session, actor, project)
        return subjects.role_ids, subjects.team_ids

    return await fields.build_field_ctx(
        session,
        definitions,
        project,
        user_id=actor.id,
        has_manage=has_manage,
        subjects_lookup=_subjects,
    )


def _internal_visible(
    permissions_by_project: dict[uuid.UUID, frozenset[Permission]],
) -> set[uuid.UUID]:
    """Projects where the actor may see internal comments (visible-only comment_count)."""
    return {
        pid
        for pid, permissions in permissions_by_project.items()
        if Permission.COMMENT_READ_INTERNAL in permissions
    }
