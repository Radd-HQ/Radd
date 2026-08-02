"""Scalar settings resolution (specs 50/67): project → instance → env.

`resolve()` is the single read seam; consumers that used `config.settings.<x>`
directly for a registered key call this instead so per-scope overrides apply.
Absence of any row returns the env/config default, so switching a consumer over
is behaviour-preserving until an override is written.
"""

import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError

from .models import ScopedSetting
from .types import SETTINGS_REGISTRY, SettingKey, SettingScope, SettingSpec, SettingType


def _coerce(spec: SettingSpec, value: Any) -> Any:
    """Normalise a stored/incoming value to the spec's declared type; an
    enumerated setting rejects values outside its choices (409) — a typo must
    never reach a StrEnum coercion at read time."""
    if spec.type is SettingType.INT:
        return int(value)
    if spec.type is SettingType.BOOL:
        return bool(value)
    text = str(value)
    if spec.choices is not None and text not in spec.choices:
        raise ConflictError(
            "scoped_setting",
            reason=f"'{spec.key.value}' must be one of: {', '.join(spec.choices)}",
        )
    return text


def _lookup_order(spec: SettingSpec, project_id: uuid.UUID | None) -> list[tuple[str, uuid.UUID | None]]:
    """(scope, scope_id) pairs to try, narrowest first — restricted to the scopes the
    spec allows, so a stale narrower row can never shadow an instance-only key."""
    order: list[tuple[str, uuid.UUID | None]] = []
    if project_id is not None and SettingScope.PROJECT in spec.scopes:
        order.append((SettingScope.PROJECT.value, project_id))
    order.append((SettingScope.INSTANCE.value, None))
    return order


async def resolve(
    session: AsyncSession,
    key: SettingKey,
    *,
    project_id: uuid.UUID | None = None,
) -> Any:
    """The effective value of `key` in the given scope: the project override if
    one exists, else the instance override, else the env/config default."""
    spec = SETTINGS_REGISTRY[key]
    order = _lookup_order(spec, project_id)
    conditions = [
        and_(ScopedSetting.scope == scope, ScopedSetting.scope_id.is_(None))
        if scope_id is None
        else and_(ScopedSetting.scope == scope, ScopedSetting.scope_id == scope_id)
        for scope, scope_id in order
    ]
    rows = (
        await session.execute(
            select(ScopedSetting.scope, ScopedSetting.scope_id, ScopedSetting.value).where(
                ScopedSetting.key == key.value, or_(*conditions)
            )
        )
    ).all()
    found = {(scope, scope_id): value for scope, scope_id, value in rows}
    for scope, scope_id in order:
        if (scope, scope_id) in found:
            return _coerce(spec, found[(scope, scope_id)])
    return spec.default


async def set_value(
    session: AsyncSession,
    key: SettingKey,
    scope: SettingScope,
    scope_id: uuid.UUID | None,
    value: Any,
) -> Any:
    """Upsert one override. Raises ConflictError if the key isn't settable at
    `scope` or `scope_id` is inconsistent with it (instance = no id, project = id)."""
    spec = SETTINGS_REGISTRY[key]
    if scope not in spec.scopes:
        raise ConflictError(
            "scoped_setting", reason=f"'{key.value}' cannot be set at {scope.value} scope"
        )
    if (scope is SettingScope.INSTANCE) != (scope_id is None):
        raise ConflictError(
            "scoped_setting", reason="instance scope takes no id; project scope requires one"
        )
    coerced = _coerce(spec, value)
    existing = await session.scalar(
        select(ScopedSetting).where(
            ScopedSetting.scope == scope.value,
            ScopedSetting.scope_id.is_(None) if scope_id is None else ScopedSetting.scope_id == scope_id,
            ScopedSetting.key == key.value,
        )
    )
    if existing is None:
        session.add(
            ScopedSetting(scope=scope.value, scope_id=scope_id, key=key.value, value=coerced)
        )
    else:
        existing.value = coerced
    await session.flush()
    return coerced


async def clear_value(
    session: AsyncSession, key: SettingKey, scope: SettingScope, scope_id: uuid.UUID | None
) -> None:
    """Remove an override so the wider scope (or env default) takes over again."""
    existing = await session.scalar(
        select(ScopedSetting).where(
            ScopedSetting.scope == scope.value,
            ScopedSetting.scope_id.is_(None) if scope_id is None else ScopedSetting.scope_id == scope_id,
            ScopedSetting.key == key.value,
        )
    )
    if existing is not None:
        await session.delete(existing)
        await session.flush()


async def list_for_scope(
    session: AsyncSession, scope: SettingScope, scope_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Every registered setting applicable at `scope`, with its effective value
    (resolved through the cascade) and whether it is overridden *here*."""
    project_id = scope_id if scope is SettingScope.PROJECT else None
    set_here = {
        row_key
        for row_key in (
            await session.execute(
                select(ScopedSetting.key).where(
                    ScopedSetting.scope == scope.value,
                    ScopedSetting.scope_id.is_(None)
                    if scope_id is None
                    else ScopedSetting.scope_id == scope_id,
                )
            )
        ).scalars()
    }
    result = []
    for key, spec in SETTINGS_REGISTRY.items():
        if scope not in spec.scopes:
            continue
        effective = await resolve(session, key, project_id=project_id)
        result.append(
            {
                "key": key.value,
                "type": spec.type.value,
                "label": spec.label,
                "description": spec.description,
                "value": effective,
                "set_here": key.value in set_here,
                "default": spec.default,
                "choices": list(spec.choices) if spec.choices else None,
            }
        )
    return result
