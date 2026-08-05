"""kernel.entities — declarative entity registration + auto-wiring (§0.5).

A plugin declares an `EntitySpec` (a field DSL, or a code-defined `model` via the
escape hatch); the kernel builds the model into `Base.metadata`, and AUTO-WIRES —
with no further plugin code — a generic permission-guarded CRUD router, the
`<key>.created/updated/deleted` event types (which flow straight into automations
+ webhooks + audit), and the `<key>.create/update/delete` CRUD-resource RBAC atoms.
This is the payoff of mediation: "add a milestone entity → get a first-class
feature." Model access goes only through the kernel session, so the permission and
outbox invariants hold.

The kernel imports nothing from `radd.modules.*` — at load OR inside a handler
(RADD-892). Identity, the permission gate, row visibility and event emission are
policies, resolved per request through the installed `kernel.hosts.EntityHost`.
"""

# NOTE: deliberately NOT `from __future__ import annotations` — the generated CRUD
# handlers annotate params with locally-scoped pydantic models (Create/Update/Read);
# PEP 563 string annotations would be unresolvable forward-refs to FastAPI.

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
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

from .hosts import entity_host
from .registry import registries
from .specs import (
    CrudResourceSpec,
    EntityFieldSpec,
    EntitySpec,
    EventTypeSpec,
    ProjectPurgeSpec,
)

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


def _project_purge(spec: EntitySpec) -> ProjectPurgeSpec:
    """A declared entity's table has no `ON DELETE CASCADE` — `_column` never
    emits one — so a project cannot be deleted while its rows exist. Registering
    the purge HERE is what makes the north-star promise hold in both directions:
    a plugin that writes no model code also writes no teardown code, and the
    hardcoded child list that predated this (jiraimport's `_PROJECT_CHILDREN`)
    could never have known the table existed. Order 10: entity rows are leaves.
    """
    return ProjectPurgeSpec(name=f"entity:{spec.key}", tables=(spec.table,), order=10)


def register_entity(spec: EntitySpec) -> type:
    """Auto-wire an entity: build the model + register its CRUD-resource RBAC atoms
    and created/updated/deleted event types into the kernel registries. Idempotent."""
    model = build_model(spec)
    registries.crud_resources.setdefault(spec.key, _crud_resource(spec))
    for et in _event_types(spec):
        registries.event_types.setdefault(et.event_type, et)
    if spec.project_scoped:
        purge = _project_purge(spec)
        registries.project_purges.setdefault(purge.name, purge)
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


async def _acting_user(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
):
    """The caller, resolved through the host at REQUEST time.

    A kernel-owned dependency with a fixed signature is what lets the generated
    routers be built while plugins are still loading: FastAPI needs a callable at
    decoration time, and `auth.deps.CurrentUser` would have to be imported then —
    the very dependency this file is here to shed.
    """
    return await entity_host().current_user(request, session)


def crud_router(spec: EntitySpec) -> APIRouter:
    """A full CRUD router for the entity — permission-guarded by its own atoms,
    emitting its own events. The plugin writes none of this."""
    model = build_model(spec)
    Create, Update, Read = _pydantic_models(spec)
    plural = spec.plural or f"{spec.key}s"
    router = APIRouter(prefix=f"/{plural}", tags=[plural])
    Session = Annotated[AsyncSession, Depends(get_session)]
    User = Annotated[Any, Depends(_acting_user)]
    key = spec.key
    project_scoped = spec.project_scoped

    async def _require(session: AsyncSession, user, obj_or_pid, atom: str) -> None:
        pid = None
        if project_scoped:
            pid = obj_or_pid if isinstance(obj_or_pid, uuid.UUID) else obj_or_pid.project_id
        await entity_host().require(session, user, atom, project_id=pid)

    async def _emit(session: AsyncSession, verb: str, obj, actor_id) -> None:
        payload = {"id": str(obj.id)}
        if project_scoped:
            payload["project_id"] = str(obj.project_id)
        await entity_host().emit(
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
        stmt = select(model)
        if project_scoped and project_id is not None:
            stmt = stmt.where(model.project_id == project_id)
        rows = list((await session.execute(stmt.order_by(model.created_at.desc()))).scalars())
        # Row visibility is the host's call, not the kernel's: it means item.read
        # per row's project plus (RADD-817) whatever RelationSpecs the plugin
        # registered for this entity key.
        if project_scoped:
            rows = await entity_host().visible_rows(session, user, key, rows)
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
