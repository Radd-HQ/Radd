"""Running a body, the interpreter and its packages: the plugin's public seam
(RADD-1269; the script library went with RADD-1272 — a script lives on its node)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.config import settings
from radd.exceptions import NotFoundError
from radd.kernel import changes
from radd.modules.auth import service_tokens
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.items import service as items

from . import interpreter, runner
from .models import ScriptInterpreter, ScriptPackage
from .schemas import InterpreterRead, InterpreterSettings, PackageCreate, RunRequest
from .types import InterpreterStatus, PackageStatus, ScriptEntity, ScriptEvent

logger = logging.getLogger(__name__)

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
            {**payload, "radd_url": settings.scripts_api_url or settings.app_base_url, "radd_token": raw},
            timeout=timeout,
            python=python,
        )
    finally:
        try:
            await service_tokens.discard_token(session, await session.get(token.__class__, token.id))
            await session.commit()
        except Exception:  # the expiry covers a key that outlives a failed discard
            logger.warning("scripts: could not discard the run key for %s; it expires anyway", label)


async def run_test(session: AsyncSession, data: RunRequest, actor: User) -> runner.Outcome:
    """The inspector's Test box: the body as typed, seeded with one item when a
    key is given, as the caller."""
    loaded: list[dict[str, Any]] = []
    if data.item_key.strip():
        read = await items.get_item_by_key(session, data.item_key.strip().upper(), actor)
        loaded.append(read.model_dump(mode="json"))
    payload = {
        "event": None,
        "items": loaded,
        "vars": data.vars,
        "params": data.params,
        "subject_ids": [entry["id"] for entry in loaded],
        "actor": {"id": str(actor.id), "name": actor.name, "email": actor.email},
    }
    return await run_body(session, data.body, payload, actor=actor, timeout=data.timeout, label="test")


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
        wheelhouses=[str(path) for path in interpreter.wheelhouses()],
        operator_wheelhouse=str(interpreter.root() / interpreter.WHEELHOUSE_DIR),
        index_url=interpreter.masked_url(row.index_url),
        offline=row.offline,
    )


_SETTINGS_FIELDS = ("index_url", "offline")


async def update_interpreter_settings(
    session: AsyncSession, data: InterpreterSettings, actor_id: uuid.UUID | None
) -> InterpreterRead:
    """Where packages resolve from. Takes effect on the next install; the ledger
    shows the URL with its password masked, since a mirror may want one."""
    row = await _interpreter_row(session)
    before = changes.snapshot(row, _SETTINGS_FIELDS)
    row.index_url = data.index_url
    row.offline = data.offline
    await session.flush()
    after = changes.snapshot(row, _SETTINGS_FIELDS)
    for side in (before, after):
        side["index_url"] = interpreter.masked_url(side["index_url"])
    await events.emit(
        session,
        event_type=ScriptEvent.INTERPRETER_UPDATED,
        entity_type=ScriptEntity.INTERPRETER,
        entity_id=uuid.UUID(int=1),
        actor_id=actor_id,
        payload={"index_url": after["index_url"], "offline": row.offline},
        changes=changes.diff(before, after, labels={"index_url": "Package index", "offline": "Offline"}),
    )
    return await interpreter_read(session)


async def rebuild_interpreter(session: AsyncSession, python_version: str, actor_id: uuid.UUID | None) -> InterpreterRead:
    """Rebuild the venv, then reinstall every package row into it."""
    row = await _interpreter_row(session)
    row.python_version = python_version
    result = await interpreter.rebuild(python_version, index_url=row.index_url, offline=row.offline)
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
        await _install_row(session, package, row)
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


async def _install_row(session: AsyncSession, package: ScriptPackage, row: ScriptInterpreter) -> None:
    result = await interpreter.install(package.spec, index_url=row.index_url, offline=row.offline)
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
    await _install_row(session, package, await _interpreter_row(session))
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
