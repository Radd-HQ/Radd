"""Scripts, packages and the interpreter: the plugin's public seam (RADD-1269)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.auth import service_tokens
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.items import service as items

from . import interpreter, runner
from .models import Script, ScriptInterpreter, ScriptPackage, ScriptVersion
from .schemas import (
    InterpreterRead,
    PackageCreate,
    RunRequest,
    ScriptCreate,
    ScriptUpdate,
)
from .types import InterpreterStatus, PackageStatus, ScriptEntity, ScriptEvent

logger = logging.getLogger(__name__)

SCRIPT_FIELDS: tuple[str, ...] = ("name", "description", "body", "version")


# --- scripts -----------------------------------------------------------------


async def list_scripts(session: AsyncSession) -> list[Script]:
    return list((await session.execute(select(Script).order_by(Script.name))).scalars())


async def get_script(session: AsyncSession, script_id: uuid.UUID) -> Script:
    row = await session.get(Script, script_id)
    if row is None:
        raise NotFoundError(ScriptEntity.SCRIPT, script_id)
    return row


async def script_by_name(session: AsyncSession, name: str) -> Script | None:
    return (
        await session.execute(select(Script).where(Script.name == name.strip()))
    ).scalar_one_or_none()


async def _write_version(session: AsyncSession, script: Script, actor_id: uuid.UUID | None, note: str) -> None:
    script.version = (script.version or 0) + 1
    session.add(
        ScriptVersion(
            script_id=script.id,
            version=script.version,
            body=script.body,
            note=(note or "")[:2000],
            created_by_id=actor_id,
            created_at=utcnow(),
        )
    )
    await session.flush()


async def create_script(session: AsyncSession, data: ScriptCreate, actor_id: uuid.UUID | None) -> Script:
    if await script_by_name(session, data.name) is not None:
        raise ConflictError(ScriptEntity.SCRIPT, reason=f"a script named {data.name!r} already exists")
    script = Script(name=data.name, description=data.description, body=data.body, version=0, updated_by_id=actor_id)
    session.add(script)
    await session.flush()
    await _write_version(session, script, actor_id, data.note)
    await events.emit(
        session,
        event_type=ScriptEvent.CREATED,
        entity_type=ScriptEntity.SCRIPT,
        entity_id=script.id,
        actor_id=actor_id,
        payload={"name": script.name},
    )
    return script


async def update_script(
    session: AsyncSession, script_id: uuid.UUID, data: ScriptUpdate, actor_id: uuid.UUID | None
) -> Script:
    script = await get_script(session, script_id)
    before = changes.snapshot(script, SCRIPT_FIELDS)
    if data.name is not None and data.name != script.name:
        if await script_by_name(session, data.name) is not None:
            raise ConflictError(ScriptEntity.SCRIPT, reason=f"a script named {data.name!r} already exists")
        script.name = data.name
    if data.description is not None:
        script.description = data.description
    body_changed = data.body is not None and data.body != script.body
    if body_changed:
        script.body = data.body or ""
    script.updated_by_id = actor_id
    await session.flush()
    if body_changed:
        await _write_version(session, script, actor_id, data.note)
    await events.emit(
        session,
        event_type=ScriptEvent.UPDATED,
        entity_type=ScriptEntity.SCRIPT,
        entity_id=script.id,
        actor_id=actor_id,
        payload={"name": script.name},
        # The body is code, and a diff of it in the ledger would be the size of
        # the script: "changed" is the honest record, the versions are the diff.
        changes=changes.diff_object(script, before, hidden=("body",)),
    )
    return script


async def delete_script(session: AsyncSession, script_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    script = await get_script(session, script_id)
    await events.emit(
        session,
        event_type=ScriptEvent.DELETED,
        entity_type=ScriptEntity.SCRIPT,
        entity_id=script.id,
        actor_id=actor_id,
        payload={"name": script.name},
    )
    await session.delete(script)
    await session.flush()


async def list_versions(session: AsyncSession, script_id: uuid.UUID) -> list[ScriptVersion]:
    return list(
        (
            await session.execute(
                select(ScriptVersion)
                .where(ScriptVersion.script_id == script_id)
                .order_by(ScriptVersion.version.desc())
            )
        ).scalars()
    )


# --- running -----------------------------------------------------------------


async def packet_payload(
    session: AsyncSession,
    *,
    actor: User,
    subject_ids: list[uuid.UUID],
    facts: Any,
    variables: dict[str, dict[str, str]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """What a script is handed. Items are FULL read models, loaded as the
    actor — so a script sees exactly what the automation's identity may see."""
    loaded: list[dict[str, Any]] = []
    for item_id in subject_ids[: settings.scripts_max_items]:
        try:
            read = await items.get_item(session, item_id, actor=actor)
        except Exception:  # an item the actor cannot read, or one that has gone: left out, said in the count
            logger.info("scripts: item %s not readable by %s — left out of the packet", item_id, actor.email)
            continue
        loaded.append(read.model_dump(mode="json"))
    event = None
    if facts is not None and getattr(facts, "event_type", ""):
        event = {
            "event_type": facts.event_type,
            "actor": {"id": facts.actor_id, "email": facts.actor_email, "name": facts.actor_name},
            "payload": dict(facts.payload or {}),
        }
    return {
        "event": event,
        "items": loaded,
        "vars": variables,
        "params": params,
        "subject_ids": [str(i) for i in subject_ids],
        "actor": {"id": str(actor.id), "name": actor.name, "email": actor.email},
    }


async def run_body(
    session: AsyncSession,
    body: str,
    payload: dict[str, Any],
    *,
    actor: User,
    timeout: float,
    label: str,
    python: str | None = None,
) -> runner.Outcome:
    """Mint the run's key, run, discard the key — whatever happened."""
    token, raw = await service_tokens.mint_ephemeral_token(
        session, actor, name=f"script run ({label})", ttl_seconds=int(timeout) + 60
    )
    # The key must be VISIBLE to the request the child makes, which arrives on
    # another connection: flush is not enough, the row has to be committed. A
    # nested transaction does not help either, so this is the one place in the
    # engine that commits mid-run — and it is why the mint is its own row
    # rather than a claim on the caller's session.
    await session.commit()
    try:
        return await runner.run(
            body,
            {**payload, "radd_url": settings.app_base_url, "radd_token": raw},
            timeout=timeout,
            python=python,
        )
    finally:
        try:
            await service_tokens.discard_token(session, await session.get(token.__class__, token.id))
            await session.commit()
        except Exception:  # the expiry covers a key that outlives a failed discard
            logger.warning("scripts: could not discard the run key for %s; it expires anyway", label)


async def run_now(session: AsyncSession, script: Script, data: RunRequest, actor: User) -> runner.Outcome:
    """The settings page's Run now box: a pasted packet against the real API."""
    payload = {
        "event": data.event,
        "items": data.items,
        "vars": data.vars,
        "params": data.params,
        "subject_ids": [str(item.get("id")) for item in data.items if item.get("id")],
        "actor": {"id": str(actor.id), "name": actor.name, "email": actor.email},
    }
    return await run_body(session, script.body, payload, actor=actor, timeout=data.timeout, label=f"run now: {script.name}")


# --- the interpreter ---------------------------------------------------------


async def _interpreter_row(session: AsyncSession) -> ScriptInterpreter:
    row = await session.get(ScriptInterpreter, 1)
    if row is None:
        row = ScriptInterpreter(id=1, python_version=settings.scripts_default_python)
        session.add(row)
        await session.flush()
    return row


async def interpreter_read(session: AsyncSession) -> InterpreterRead:
    row = await _interpreter_row(session)
    status = row.status
    if status == InterpreterStatus.READY and not interpreter.ready():
        status = InterpreterStatus.MISSING  # the volume went away under us
    return InterpreterRead(
        python_version=row.python_version,
        status=status,
        resolved=row.resolved,
        log=row.log,
        built_at=row.built_at,
        path=str(interpreter.venv_dir()),
        available=await interpreter.available_versions(),
        sdk_source=interpreter.sdk_source(),
    )


async def rebuild_interpreter(session: AsyncSession, python_version: str, actor_id: uuid.UUID | None) -> InterpreterRead:
    """Rebuild the venv, then reinstall every package row into it."""
    row = await _interpreter_row(session)
    row.python_version = python_version
    result = await interpreter.rebuild(python_version)
    row.log = result.output
    row.built_at = utcnow()
    if not result.ok:
        row.status = InterpreterStatus.FAILED
        row.resolved = ""
        await session.flush()
        return await interpreter_read(session)
    row.status = InterpreterStatus.READY
    row.resolved = await interpreter.resolved_python()
    await session.flush()
    for package in await list_packages(session):
        await _install_row(session, package)
    await events.emit(
        session,
        event_type=ScriptEvent.INTERPRETER_REBUILT,
        entity_type=ScriptEntity.INTERPRETER,
        entity_id=uuid.UUID(int=1),
        actor_id=actor_id,
        payload={"python_version": python_version, "resolved": row.resolved},
    )
    return await interpreter_read(session)


# --- packages ----------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def package_name(spec: str) -> str:
    """The distribution name inside a requirement, normalised the way pip does."""
    match = _NAME_RE.match(spec.strip())
    name = match.group(0) if match else spec.strip()
    return re.sub(r"[-_.]+", "-", name).lower()


async def list_packages(session: AsyncSession) -> list[ScriptPackage]:
    return list((await session.execute(select(ScriptPackage).order_by(ScriptPackage.name))).scalars())


async def _install_row(session: AsyncSession, package: ScriptPackage) -> None:
    result = await interpreter.install(package.spec)
    package.log = result.output
    if result.ok:
        package.status = PackageStatus.INSTALLED
        package.resolved_version = await interpreter.installed_version(package.name)
        package.installed_at = utcnow()
    else:
        package.status = PackageStatus.FAILED
        package.resolved_version = ""
    await session.flush()


async def add_package(session: AsyncSession, data: PackageCreate, actor_id: uuid.UUID | None) -> ScriptPackage:
    name = package_name(data.spec)
    existing = (await session.execute(select(ScriptPackage).where(ScriptPackage.name == name))).scalar_one_or_none()
    if existing is not None:
        existing.spec = data.spec
        package = existing
    else:
        package = ScriptPackage(name=name, spec=data.spec, status=PackageStatus.PENDING, created_at=utcnow())
        session.add(package)
        await session.flush()
    await _install_row(session, package)
    await events.emit(
        session,
        event_type=ScriptEvent.PACKAGE_INSTALLED,
        entity_type=ScriptEntity.PACKAGE,
        entity_id=package.id,
        actor_id=actor_id,
        payload={"name": package.name, "spec": package.spec, "status": package.status, "resolved": package.resolved_version},
    )
    return package


async def remove_package(session: AsyncSession, package_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    package = await session.get(ScriptPackage, package_id)
    if package is None:
        raise NotFoundError(ScriptEntity.PACKAGE, package_id)
    result = await interpreter.uninstall(package.name)
    if not result.ok and interpreter.ready():
        logger.warning("scripts: uninstall of %s said: %s", package.name, result.output[-300:])
    await events.emit(
        session,
        event_type=ScriptEvent.PACKAGE_REMOVED,
        entity_type=ScriptEntity.PACKAGE,
        entity_id=package.id,
        actor_id=actor_id,
        payload={"name": package.name},
    )
    await session.delete(package)
    await session.flush()
