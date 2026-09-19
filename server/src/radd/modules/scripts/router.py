"""Settings → Scripts (RADD-1269): the interpreter, the packages, the scripts.

Literal paths (`/interpreter`, `/packages`) are declared BEFORE `/{script_id}`
— Starlette matches in declaration order, and a literal declared after a
parameter path answers a 422 about parsing the word as a UUID (RADD-761).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import (
    InterpreterRead,
    InterpreterRebuild,
    PackageCreate,
    PackageRead,
    RunOutcomeRead,
    RunRequest,
    ScriptCreate,
    ScriptRead,
    ScriptSummary,
    ScriptUpdate,
    ScriptVersionRead,
)
from .types import PERM_MANAGE, STARTER_SCRIPT

router = APIRouter(prefix="/scripts", tags=["scripts"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _manage(session: AsyncSession, user) -> None:
    await authz.require(session, user, PERM_MANAGE)


@router.get("/interpreter", response_model=InterpreterRead)
async def get_interpreter(session: Session, user: CurrentUser) -> InterpreterRead:
    await _manage(session, user)
    return await service.interpreter_read(session)


@router.post("/interpreter/rebuild", response_model=InterpreterRead)
async def rebuild_interpreter(data: InterpreterRebuild, session: Session, user: CurrentUser) -> InterpreterRead:
    """Recreate the venv for a Python version and reinstall every package."""
    await _manage(session, user)
    return await service.rebuild_interpreter(session, data.python_version, user.id)


@router.get("/packages", response_model=list[PackageRead])
async def list_packages(session: Session, user: CurrentUser) -> list[PackageRead]:
    await _manage(session, user)
    return [PackageRead.model_validate(row) for row in await service.list_packages(session)]


@router.post("/packages", response_model=PackageRead, status_code=201)
async def add_package(data: PackageCreate, session: Session, user: CurrentUser) -> PackageRead:
    await _manage(session, user)
    return PackageRead.model_validate(await service.add_package(session, data, user.id))


@router.delete("/packages/{package_id}", status_code=204)
async def remove_package(package_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await _manage(session, user)
    await service.remove_package(session, package_id, user.id)


@router.get("/starter", response_model=dict)
async def starter(session: Session, user: CurrentUser) -> dict:
    """The author contract as a starter script, for the New script button."""
    await _manage(session, user)
    return {"body": STARTER_SCRIPT}


@router.get("", response_model=list[ScriptSummary])
async def list_scripts(session: Session, user: CurrentUser) -> list[ScriptSummary]:
    await _manage(session, user)
    return [ScriptSummary.model_validate(row) for row in await service.list_scripts(session)]


@router.post("", response_model=ScriptRead, status_code=201)
async def create_script(data: ScriptCreate, session: Session, user: CurrentUser) -> ScriptRead:
    await _manage(session, user)
    return ScriptRead.model_validate(await service.create_script(session, data, user.id))


@router.get("/{script_id}", response_model=ScriptRead)
async def get_script(script_id: uuid.UUID, session: Session, user: CurrentUser) -> ScriptRead:
    await _manage(session, user)
    return ScriptRead.model_validate(await service.get_script(session, script_id))


@router.patch("/{script_id}", response_model=ScriptRead)
async def update_script(script_id: uuid.UUID, data: ScriptUpdate, session: Session, user: CurrentUser) -> ScriptRead:
    await _manage(session, user)
    return ScriptRead.model_validate(await service.update_script(session, script_id, data, user.id))


@router.delete("/{script_id}", status_code=204)
async def delete_script(script_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await _manage(session, user)
    await service.delete_script(session, script_id, user.id)


@router.get("/{script_id}/versions", response_model=list[ScriptVersionRead])
async def list_versions(script_id: uuid.UUID, session: Session, user: CurrentUser) -> list[ScriptVersionRead]:
    await _manage(session, user)
    await service.get_script(session, script_id)
    return [ScriptVersionRead.model_validate(row) for row in await service.list_versions(session, script_id)]


@router.post("/{script_id}/run", response_model=RunOutcomeRead)
async def run_script(script_id: uuid.UUID, data: RunRequest, session: Session, user: CurrentUser) -> RunOutcomeRead:
    """Run now: the pasted packet, the real API, as the caller."""
    await _manage(session, user)
    script = await service.get_script(session, script_id)
    outcome = await service.run_now(session, script, data, user)
    return RunOutcomeRead(
        ok=outcome.ok, result=outcome.result, stdout=outcome.stdout, stderr=outcome.stderr,
        error=outcome.error, duration_ms=outcome.duration_ms,
    )
