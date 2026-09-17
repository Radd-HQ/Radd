"""Plan lifecycle (spec 100) — create from a snapshot, read, edit, validate.

Creating a plan PROFILES the snapshot and pre-fills every mapping table, so the
admin opens on suggestions rather than a blank sheet. Re-suggesting is a separate
action that keeps the choices already made.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import service as auth_service
from radd.modules.fields import service as fields_service
from radd.modules.fields.types import FieldType
from radd.modules.linktypes import service as linktypes_service
from radd.modules.projects import service as projects_service
from radd.modules.workflow import service as workflow_service
from radd.modules.itemtypes import service as itemtypes_service

from .. import connections, profile as profile_mod
from ..models import JiraConnection, JiraPlan, JiraSnapshot
from ..snapshot import service as snapshot_service
from ..types import JiraEntity, VocabAction
from . import suggest, validate as validate_mod
from .schemas import PlanCreate, PlanMappings, PlanOptions, PlanProblem, PlanUpdate


async def list_plans(session: AsyncSession) -> list[JiraPlan]:
    result = await session.execute(select(JiraPlan).order_by(JiraPlan.created_at.desc()))
    return list(result.scalars())


async def get_plan(session: AsyncSession, plan_id: uuid.UUID) -> JiraPlan:
    plan = await session.get(JiraPlan, plan_id)
    if plan is None:
        raise NotFoundError(JiraEntity.IMPORT_PLAN, plan_id)
    return plan


async def create_plan(session: AsyncSession, data: PlanCreate) -> JiraPlan:
    """A new plan, pre-filled by profiling the snapshot."""
    await _ensure_name_free(session, data.name)
    snapshot = await snapshot_service.require_complete(session, data.snapshot_id)
    mappings = await build_suggestions(session, snapshot)
    plan = JiraPlan(
        name=data.name,
        snapshot_id=snapshot.id,
        radd_project_key=data.radd_project_key.upper(),
        radd_project_name=data.radd_project_name,
        mappings=mappings.model_dump(mode="json"),
        options=PlanOptions().model_dump(mode="json"),
    )
    session.add(plan)
    await session.flush()
    return plan


async def update_plan(session: AsyncSession, plan_id: uuid.UUID, data: PlanUpdate) -> JiraPlan:
    plan = await get_plan(session, plan_id)
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] != plan.name:
        await _ensure_name_free(session, fields["name"])
        plan.name = fields["name"]
    if data.radd_project_key is not None:
        plan.radd_project_key = data.radd_project_key.upper()
    if data.radd_project_name is not None:
        plan.radd_project_name = data.radd_project_name
    if data.mappings is not None:
        plan.mappings = data.mappings.model_dump(mode="json")
    if data.options is not None:
        plan.options = data.options.model_dump(mode="json")
    await session.flush()
    return plan


async def delete_plan(session: AsyncSession, plan_id: uuid.UUID) -> None:
    await session.delete(await get_plan(session, plan_id))
    await session.flush()


async def build_suggestions(session: AsyncSession, snapshot: JiraSnapshot) -> PlanMappings:
    """Profile the cache and suggest a mapping for everything in it."""
    inbound = await profile_mod.build(session, snapshot)
    users = await auth_service.list_users(session)
    catalog = await linktypes_service.catalog(session)
    definitions = await fields_service.list_fields(session)
    connection = (
        await session.get(JiraConnection, snapshot.connection_id)
        if snapshot.connection_id
        else None
    )
    return suggest.build(
        inbound,
        existing_field_keys={d.key for d in definitions},
        # So a MAP into a select can offer to ADD the values it is missing.
        existing_field_options={d.key: list(d.options or []) for d in definitions if d.options},
        users_by_email={u.email.lower(): u.id for u in users},
        # Name matches are ambiguous by nature, so a duplicated display name is
        # dropped from the index rather than matched to whichever came first.
        users_by_name=_unique_by_name(users),
        existing_link_type_keys=set(catalog),
        placeholder_domain=(
            connections.placeholder_email_domain(connection) if connection else ""
        ),
        # Leavers: matched, imported, and flagged — never silently reactivated.
        inactive_user_ids={u.id for u in users if not u.active},
    )


def _unique_by_name(users: list) -> dict[str, uuid.UUID]:
    counts: dict[str, int] = {}
    index: dict[str, uuid.UUID] = {}
    for user in users:
        name = (user.name or "").strip().lower()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        index[name] = user.id
    return {name: uid for name, uid in index.items() if counts[name] == 1}


async def validate_plan(session: AsyncSession, plan: JiraPlan) -> list[PlanProblem]:
    catalog = await linktypes_service.catalog(session)
    definitions = await fields_service.list_fields(session)
    # Fields that exist but are scoped away from the target project. Only knowable
    # once the project exists, so an unprovisioned plan reports none.
    out_of_scope = set()
    if plan.radd_project_id is not None:
        out_of_scope = {
            d.key
            for d in definitions
            if d.project_ids and plan.radd_project_id not in d.project_ids
        }
    result = validate_mod.validate(
        mappings(plan),
        existing_fields={d.key: FieldType(d.type) for d in definitions},
        existing_link_type_keys=set(catalog),
        out_of_scope_fields=out_of_scope,
    )

    try:
        target = await projects_service.get_by_key(session, plan.radd_project_key)
    except NotFoundError:
        target = None
    states = await workflow_service.list_states(session, target.id) if target else []
    types = await itemtypes_service.list_types(session, target.id) if target else []
    for section, entries, names, attr in (
        ("statuses", mappings(plan).statuses, {s.name.strip().lower() for s in states}, "state_name"),
        ("issue_types", mappings(plan).issue_types, {t.name.strip().lower() for t in types}, "type_name"),
    ):
        for entry in entries:
            if entry.action is VocabAction.MAP and getattr(entry, attr).strip().lower() not in names:
                result.append(PlanProblem(section=section, subject=entry.jira,
                    message="Choose an existing target in this project, or choose Create."))
    return result


def mappings(plan: JiraPlan) -> PlanMappings:
    return PlanMappings.model_validate(plan.mappings or {})


def options(plan: JiraPlan) -> PlanOptions:
    return PlanOptions.model_validate(plan.options or {})


async def _ensure_name_free(session: AsyncSession, name: str) -> None:
    result = await session.execute(select(JiraPlan).where(JiraPlan.name == name))
    if result.scalar_one_or_none() is not None:
        raise ConflictError(JiraEntity.IMPORT_PLAN, reason=f"a plan named {name!r} exists")
