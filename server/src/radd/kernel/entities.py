"""kernel.entities — declarative entity registration + auto-wiring (§0.5).

A plugin declares an `EntitySpec` (a field DSL, or a code-defined `model` via the
escape hatch); the kernel builds the model into `Base.metadata`, and AUTO-WIRES —
with no further plugin code — a generic permission-guarded CRUD router, the
`<key>.created/updated/deleted` event types (which flow straight into automations
+ webhooks + audit), and the `<key>.create/update/delete` CRUD-resource RBAC atoms.
This is the payoff of mediation: "add a milestone entity → get a first-class
feature." Model access goes only through the kernel session, so the permission and
outbox invariants hold.

The kernel imports nothing from `radd.modules.*` at module load; the CRUD handlers
reach auth/projects/events through deferred imports (the codebase's cross-module idiom).
"""

# NOTE: deliberately NOT `from __future__ import annotations` — the generated CRUD
# handlers annotate params with locally-scoped pydantic models (Create/Update/Read);
# PEP 563 string annotations would be unresolvable forward-refs to FastAPI.

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import ConfigDict, create_model
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Uuid,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import Base, get_session

from .registry import registries
from .specs import CrudResourceSpec, EntityFieldSpec, EntitySpec, EventTypeSpec

# EntityFieldSpec.type → (SQLAlchemy column type, python type for pydantic)
_TYPES: dict[str, tuple[Any, Any]] = {
    "str": (String(255), str),
    "text": (Text, str),
    "int": (Integer, int),
    "float": (Float, float),
    "bool": (Boolean, bool),
    "uuid": (Uuid, uuid.UUID),
    "datetime": (DateTime, datetime),
    "date": (Date, date),
    "json": (JSON, Any),
}

_models: dict[str, type] = {}  # entity key → mapped class (idempotent across reloads)


def _column(f: EntityFieldSpec) -> Column:
    coltype, _ = _TYPES[f.type]
    args: list[Any] = [f.name, coltype]
    if f.fk:
        args.append(ForeignKey(f.fk))
    kwargs: dict[str, Any] = {"nullable": f.nullable, "index": f.index, "unique": f.unique}
    if f.default is not None:
        kwargs["default"] = f.default
    return Column(*args, **kwargs)


def build_model(spec: EntitySpec) -> type:
    """Build (once) a mapped class for the entity — the escape hatch `spec.model`
    wins; otherwise map a Table imperatively from the field DSL. Idempotent: the
    table lands in Base.metadata exactly once even across loader reloads."""
    if spec.model is not None:
        _models[spec.key] = spec.model
        return spec.model
    if spec.key in _models:
        return _models[spec.key]
    columns = [
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("created_at", DateTime, server_default=func.now()),
        Column("updated_at", DateTime, server_default=func.now(), onupdate=func.now()),
        *[_column(f) for f in spec.fields],
    ]
    table = Table(spec.table, Base.metadata, *columns)
    cls = type(spec.key.title().replace("_", ""), (), {})
    # eager_defaults: fetch server-generated created_at/updated_at via RETURNING at
    # flush — without it, reading updated_at after an UPDATE lazy-loads and breaks
    # the async session (MissingGreenlet). Mirrors db.TimestampMixin.
    Base.registry.map_imperatively(cls, table, eager_defaults=True)
    _models[spec.key] = cls
    return cls


def model_for(key: str) -> type | None:
    return _models.get(key)


def _crud_resource(spec: EntitySpec) -> CrudResourceSpec:
    scope = "project" if spec.project_scoped else "global"
    return CrudResourceSpec(spec.key, scope, spec.plural or f"{spec.label}s", f"{spec.key}.manage")


def _event_types(spec: EntitySpec) -> tuple[EventTypeSpec, ...]:
    group = spec.label
    return tuple(
        EventTypeSpec(
            f"{spec.key}.{verb}",
            f"{spec.label} {verb}",
            group,
            item_scoped=False,
            has_changes=(verb == "updated"),
            entity_type=spec.key,
        )
        for verb in ("created", "updated", "deleted")
    )


def register_entity(spec: EntitySpec) -> type:
    """Auto-wire an entity: build the model + register its CRUD-resource RBAC atoms
    and created/updated/deleted event types into the kernel registries. Idempotent."""
    model = build_model(spec)
    registries.crud_resources.setdefault(spec.key, _crud_resource(spec))
    for et in _event_types(spec):
        registries.event_types.setdefault(et.event_type, et)
    return model


# --- generic permission-aware CRUD router -----------------------------------


def _pydantic_models(spec: EntitySpec):
    create_fields: dict[str, Any] = {}
    update_fields: dict[str, Any] = {}
    read_fields: dict[str, Any] = {
        "id": (uuid.UUID, ...),
        "created_at": (datetime, ...),
        "updated_at": (datetime, ...),
    }
    for f in spec.fields:
        _, pytype = _TYPES[f.type]
        optional = f.nullable or f.default is not None
        create_fields[f.name] = ((pytype | None) if f.nullable else pytype, None if optional else ...)
        update_fields[f.name] = (pytype | None, None)
        read_fields[f.name] = ((pytype | None) if f.nullable else pytype, ...)
    base = ConfigDict(from_attributes=True)
    Create = create_model(f"{spec.key}_Create", **create_fields)
    Update = create_model(f"{spec.key}_Update", **update_fields)
    Read = create_model(f"{spec.key}_Read", __config__=base, **read_fields)
    return Create, Update, Read


def crud_router(spec: EntitySpec) -> APIRouter:
    """A full CRUD router for the entity — permission-guarded by its own atoms,
    emitting its own events. The plugin writes none of this."""
    model = build_model(spec)
    Create, Update, Read = _pydantic_models(spec)
    plural = spec.plural or f"{spec.key}s"
    router = APIRouter(prefix=f"/{plural}", tags=[plural])
    Session = Annotated[AsyncSession, Depends(get_session)]
    key = spec.key
    project_scoped = spec.project_scoped

    def _current_user():
        from radd.modules.auth.deps import CurrentUser

        return CurrentUser

    User = _current_user()

    async def _require(session: AsyncSession, user, obj_or_pid, atom: str) -> None:
        from radd.modules.auth import authz

        if project_scoped:
            from radd.modules.projects import service as projects_service

            pid = obj_or_pid if isinstance(obj_or_pid, uuid.UUID) else obj_or_pid.project_id
            project = await projects_service.get_project(session, pid)
            await authz.require(session, user, atom, project=project)
        else:
            await authz.require(session, user, atom)

    async def _emit(session: AsyncSession, verb: str, obj, actor_id) -> None:
        from radd.modules.events import service as events

        payload = {"id": str(obj.id)}
        if project_scoped:
            payload["project_id"] = str(obj.project_id)
        await events.emit(
            session,
            event_type=f"{key}.{verb}",
            entity_type=key,
            entity_id=obj.id,
            actor_id=actor_id,
            payload=payload,
        )

    async def _get(session: AsyncSession, obj_id: uuid.UUID):
        from radd.exceptions import NotFoundError

        obj = await session.get(model, obj_id)
        if obj is None:
            raise NotFoundError(key, obj_id)
        return obj

    @router.post("", response_model=Read, status_code=201)
    async def create(data: Create, session: Session, user: User):  # type: ignore[valid-type]
        # exclude_unset so omitted fields fall to the column default (e.g. status).
        payload = data.model_dump(exclude_unset=True)
        await _require(session, user, payload.get("project_id"), f"{key}.create")
        obj = model(**payload)
        session.add(obj)
        await session.flush()
        await _emit(session, "created", obj, user.id)
        return Read.model_validate(obj)

    @router.get("", response_model=list[Read])
    async def list_(session: Session, user: User, project_id: uuid.UUID | None = None):  # type: ignore[valid-type]
        from radd.modules.auth import authz

        stmt = select(model)
        if project_scoped and project_id is not None:
            stmt = stmt.where(model.project_id == project_id)
        rows = list((await session.execute(stmt.order_by(model.created_at.desc()))).scalars())
        # Row visibility: item.read on each row's project (project-scoped entities).
        if project_scoped:
            from radd.kernel.registry import registries
            from radd.modules.projects import service as projects_service

            # RADD-817: the query hook for plugin relations — a plugin that
            # registered RelationSpecs for its entity key gets row-level
            # narrowing here, with the same holds_base + relation_holds_row
            # pair items use. No registered relations = the old behaviour.
            entity_relations = registries.relations_for(key)
            relation_actor = None
            visible = []
            for obj in rows:
                project = await projects_service.get_project(session, obj.project_id)
                perms = await authz.effective_permissions(session, user, project=project)
                if not authz.holds_base(perms, authz.Permission.ITEM_READ):
                    continue
                if entity_relations:
                    relations = authz.relations_held(perms, authz.Permission.ITEM_READ)
                    if authz.RELATION_ANY not in relations:
                        if relation_actor is None:
                            relation_actor = await authz.relation_actor(session, user)
                        if not authz.relation_holds_row(key, relations, relation_actor, obj):
                            continue
                visible.append(obj)
            rows = visible
        return [Read.model_validate(o) for o in rows]

    @router.get("/{obj_id}", response_model=Read)
    async def get_one(obj_id: uuid.UUID, session: Session, user: User):  # type: ignore[valid-type]
        obj = await _get(session, obj_id)
        await _require(session, user, obj, authz_read_atom())
        return Read.model_validate(obj)

    @router.patch("/{obj_id}", response_model=Read)
    async def update(obj_id: uuid.UUID, data: Update, session: Session, user: User):  # type: ignore[valid-type]
        obj = await _get(session, obj_id)
        await _require(session, user, obj, f"{key}.update")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        await session.flush()
        await _emit(session, "updated", obj, user.id)
        return Read.model_validate(obj)

    @router.delete("/{obj_id}", status_code=204)
    async def delete(obj_id: uuid.UUID, session: Session, user: User):  # type: ignore[valid-type]
        obj = await _get(session, obj_id)
        await _require(session, user, obj, f"{key}.delete")
        await _emit(session, "deleted", obj, user.id)
        await session.delete(obj)

    return router


def authz_read_atom() -> str:
    # Reads are open to project members (item.read) — value-level restriction is
    # the access-grant/field system, not CRUD atoms (spec 50 default).
    return "item.read"


async def ensure_tables() -> None:
    """Create any registered entity tables that don't exist yet (idempotent) — the
    pragmatic 'install' step for declarative entities without a dedicated migration."""
    from radd.db import engine

    tables = [m.__table__ for m in _models.values() if m.__table__ is not None]
    if not tables:
        return
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables, checkfirst=True))
