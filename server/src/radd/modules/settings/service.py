"""Scalar settings resolution (specs 50/67): project → instance → env.

`resolve()` is the single read seam; consumers that used `config.settings.<x>`
directly for a registered key call this instead so per-scope overrides apply.
Absence of any row returns the env/config default, so switching a consumer over
is behaviour-preserving until an override is written.

RADD-891: the per-key POLICY (type, scopes, prose, default source) is no
longer a static dict literal in `.types` — it is the kernel `SettingSpec` each
owning module declares via `settings_keys=(...)` on its `RaddPlugin`,
looked up live through `.types.setting_spec`/`SETTINGS_REGISTRY`.
"""

import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.kernel import SettingSpec, changes, registries
from radd.modules.events import service as events

from .models import ScopedSetting
from .types import SettingEvent, SettingKey, SettingScope, SettingsEntity, SettingType, setting_spec


def _coerce(spec: SettingSpec, value: Any) -> Any:
    """Normalise a stored/incoming value to the spec's declared type; an
    enumerated setting rejects values outside its choices (409) — a typo must
    never reach a StrEnum coercion at read time."""
    type_ = SettingType(spec.type)
    if type_ is SettingType.INT:
        return int(value)
    if type_ is SettingType.BOOL:
        return bool(value)
    text = str(value)
    if spec.choices is not None and text not in spec.choices:
        raise ConflictError(
            "scoped_setting",
            reason=f"'{spec.key}' must be one of: {', '.join(spec.choices)}",
        )
    return text


def _lookup_order(spec: SettingSpec, project_id: uuid.UUID | None) -> list[tuple[str, uuid.UUID | None]]:
    """(scope, scope_id) pairs to try, narrowest first — restricted to the scopes the
    spec allows, so a stale narrower row can never shadow an instance-only key."""
    order: list[tuple[str, uuid.UUID | None]] = []
    if project_id is not None and SettingScope.PROJECT.value in spec.scopes:
        order.append((SettingScope.PROJECT.value, project_id))
    order.append((SettingScope.INSTANCE.value, None))
    return order


async def _resolve_spec(
    session: AsyncSession, spec: SettingSpec, project_id: uuid.UUID | None
) -> Any:
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
                ScopedSetting.key == spec.key, or_(*conditions)
            )
        )
    ).all()
    found = {(scope, scope_id): value for scope, scope_id, value in rows}
    for scope, scope_id in order:
        if (scope, scope_id) in found:
            return _coerce(spec, found[(scope, scope_id)])
    return spec.default


async def resolve(
    session: AsyncSession,
    key: SettingKey,
    *,
    project_id: uuid.UUID | None = None,
) -> Any:
    """The effective value of `key` in the given scope: the project override if
    one exists, else the instance override, else the env/config default."""
    return await _resolve_spec(session, setting_spec(key), project_id)


async def set_value(
    session: AsyncSession,
    key: SettingKey,
    scope: SettingScope,
    scope_id: uuid.UUID | None,
    value: Any,
    *,
    actor_id: uuid.UUID | None = None,
) -> Any:
    """Upsert one override. Raises ConflictError if the key isn't settable at
    `scope` or `scope_id` is inconsistent with it (instance = no id, project = id)."""
    spec = setting_spec(key)
    if scope.value not in spec.scopes:
        raise ConflictError(
            "scoped_setting", reason=f"'{key.value}' cannot be set at {scope.value} scope"
        )
    if (scope is SettingScope.INSTANCE) != (scope_id is None):
        raise ConflictError(
            "scoped_setting", reason="instance scope takes no id; project scope requires one"
        )
    coerced = _coerce(spec, value)
    if spec.guard is not None:
        await spec.guard(session, coerced, actor_id)
    existing = await session.scalar(
        select(ScopedSetting).where(
            ScopedSetting.scope == scope.value,
            ScopedSetting.scope_id.is_(None) if scope_id is None else ScopedSetting.scope_id == scope_id,
            ScopedSetting.key == key.value,
        )
    )
    previous = existing.value if existing is not None else None
    if existing is None:
        session.add(
            ScopedSetting(scope=scope.value, scope_id=scope_id, key=key.value, value=coerced)
        )
    else:
        existing.value = coerced
    await session.flush()
    await _emit_changed(session, spec, key, scope, scope_id, previous, coerced, actor_id)
    return coerced


async def clear_value(
    session: AsyncSession,
    key: SettingKey,
    scope: SettingScope,
    scope_id: uuid.UUID | None,
    *,
    actor_id: uuid.UUID | None = None,
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
        previous = existing.value
        await session.delete(existing)
        await session.flush()
        await _emit_changed(
            session, setting_spec(key), key, scope, scope_id, previous, None, actor_id
        )


async def _emit_changed(
    session: AsyncSession,
    spec: SettingSpec,
    key: SettingKey,
    scope: SettingScope,
    scope_id: uuid.UUID | None,
    old: Any,
    new: Any,
    actor_id: uuid.UUID | None,
) -> None:
    """Spec 123: one `setting.changed` per effective change. A write that
    restates the stored value emits nothing — an audit row with an empty diff
    is noise to everyone downstream (the RADD-1009 rule)."""
    entry = changes.change(key.value, old, new, name=spec.label)
    if entry is None:
        return
    await events.emit(
        session,
        event_type=SettingEvent.CHANGED,
        entity_type=SettingsEntity.SETTING,
        entity_id=key.value,
        actor_id=actor_id,
        payload={"key": key.value, "scope": scope.value, "section": spec.section},
        subjects={"project": scope_id} if scope is SettingScope.PROJECT else None,
        changes=[entry],
    )


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
    for key, spec in registries.settings.items():
        if scope.value not in spec.scopes:
            continue
        effective = await _resolve_spec(session, spec, project_id)
        result.append(
            {
                "key": key,
                "type": spec.type,
                "label": spec.label,
                "description": spec.description,
                "value": effective,
                "set_here": key in set_here,
                "default": spec.default,
                "choices": list(spec.choices) if spec.choices else None,
                "secret": spec.secret,
                "section": spec.section,
            }
        )
    return result
