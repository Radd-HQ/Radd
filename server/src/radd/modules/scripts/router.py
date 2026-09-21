"""Settings → Scripts (RADD-1269): the interpreter and its packages, plus the
inspector's Test box. The script library went with RADD-1272: a script's body
lives on its automation node.
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
    InterpreterSettings,
    PackageCreate,
    PackageRead,
    RunOutcomeRead,
    RunRequest,
)
from .types import PERM_MANAGE

router = APIRouter(prefix="/scripts", tags=["scripts"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _manage(session: AsyncSession, user) -> None:
    await authz.require(session, user, PERM_MANAGE)


@router.get("/interpreter", response_model=InterpreterRead)
async def get_interpreter(session: Session, user: CurrentUser) -> InterpreterRead:
    await _manage(session, user)
    return await service.interpreter_read(session)


@router.put("/interpreter", response_model=InterpreterRead)
async def update_interpreter(data: InterpreterSettings, session: Session, user: CurrentUser) -> InterpreterRead:
    """Where packages resolve from: the admin's index and the offline switch (RADD-1277)."""
    await _manage(session, user)
    return await service.update_interpreter_settings(session, data, user.id)


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


@router.post("/run", response_model=RunOutcomeRead)
async def run_script(data: RunRequest, session: Session, user: CurrentUser) -> RunOutcomeRead:
    """The inspector's Test box: the body as typed, an optional seed item, the
    real API, as the caller."""
    await _manage(session, user)
    outcome = await service.run_test(session, data, user)
    return RunOutcomeRead(
        ok=outcome.ok, result=outcome.result, stdout=outcome.stdout, stderr=outcome.stderr,
        error=outcome.error, duration_ms=outcome.duration_ms,
    )
