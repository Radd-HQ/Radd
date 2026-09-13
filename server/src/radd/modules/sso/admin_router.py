"""Settings → Sign-in admin API (spec 110).

Instance-admin only. Every write refreshes the process-local snapshot the login
page and the kernel capability read, and drops the edited row's cached discovery
document so a changed issuer takes effect without a restart.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User

from . import idp, registry, service, references
from .models import SsoProvider
from .schemas import SsoDefaultGrant, SsoProvisioningRule, SsoProviderCreate, SsoProviderRead, SsoProviderUpdate
from .types import KIND_DEFAULTS, SsoKind

router = APIRouter(prefix="/sso", tags=["sso admin"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _require_instance_admin(actor: User) -> None:
    if not authz.is_instance_admin(actor):
        raise ForbiddenError("sign-in settings require an instance admin")


async def _read(session: AsyncSession, provider: SsoProvider) -> SsoProviderRead:
    """Async now (RADD-780/781): the starting-access template lives in two child
    tables, so a read has to fetch them rather than reflect off the row."""
    return SsoProviderRead.model_validate(provider).model_copy(
        update={
            "configured": registry.configured(provider),
            "redirect_uri": service.redirect_uri(),
            "provisioning_rules": [
                SsoProvisioningRule(
                    name=rule.name,
                    domains=rule.domains,
                    grants=[
                        SsoDefaultGrant(role_id=g.role_id, project_id=g.project_id)
                        for g in grants
                    ],
                    team_ids=team_ids,
                )
                for rule, grants, team_ids in await registry.provisioning_rules(
                    session, provider.id
                )
            ],
        }
    )


class SsoKindInfo(BaseModel):
    """What the "add a provider" form needs to prefill itself."""

    kind: SsoKind
    name: str
    issuer: str
    scopes: str


@router.post("/provisioning-references", response_model=references.ReferenceRead)
async def provisioning_references(data: references.ReferenceRequest, session: Session, user: CurrentUser) -> references.ReferenceRead:
    _require_instance_admin(user)
    return await references.read(session, data)


@router.get("/kinds", response_model=list[SsoKindInfo])
async def list_kinds(user: CurrentUser) -> list[SsoKindInfo]:
    _require_instance_admin(user)
    return [
        SsoKindInfo(kind=kind, name=d.name, issuer=d.issuer, scopes=d.scopes)
        for kind, d in KIND_DEFAULTS.items()
    ]


@router.get("/providers", response_model=list[SsoProviderRead])
async def list_providers(session: Session, user: CurrentUser) -> list[SsoProviderRead]:
    _require_instance_admin(user)
    return [await _read(session, p) for p in await registry.list_providers(session)]


@router.post("/providers", response_model=SsoProviderRead, status_code=201)
async def create_provider(
    data: SsoProviderCreate, session: Session, user: CurrentUser
) -> SsoProviderRead:
    _require_instance_admin(user)
    provider = await registry.create_provider(session, data)
    await registry.refresh_snapshot(session)
    return await _read(session, provider)


@router.patch("/providers/{provider_id}", response_model=SsoProviderRead)
async def update_provider(
    provider_id: uuid.UUID, data: SsoProviderUpdate, session: Session, user: CurrentUser
) -> SsoProviderRead:
    _require_instance_admin(user)
    provider = await registry.update_provider(session, provider_id, data)
    idp.invalidate_caches(provider_id)
    await registry.refresh_snapshot(session)
    return await _read(session, provider)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    _require_instance_admin(user)
    await registry.delete_provider(session, provider_id)
    idp.invalidate_caches(provider_id)
    await registry.refresh_snapshot(session)
    return Response(status_code=204)


class ProbeResult(BaseModel):
    ok: bool
    error: str = ""
    authorization_endpoint: str = ""


@router.post("/providers/{provider_id}/test", response_model=ProbeResult)
async def test_provider(
    provider_id: uuid.UUID, session: Session, user: CurrentUser
) -> ProbeResult:
    """Fetch the issuer's discovery document — the one thing that can be checked
    without a human completing a login. Failures come back as DATA (the admin is
    diagnosing config), never a 502. A pinned kind (GitHub) has nothing to fetch,
    so the probe simply reports the endpoints it knows."""
    _require_instance_admin(user)
    provider = await registry.get_provider(session, provider_id)
    if not registry.issuer_of(provider):
        return ProbeResult(ok=False, error="set an issuer URL")
    idp.invalidate_caches(provider_id)
    try:
        meta = await idp.metadata(provider)
    except Exception as exc:  # the probe button REPORTS failure; that is its job
        return ProbeResult(ok=False, error=f"could not reach the issuer: {exc}")
    return ProbeResult(ok=True, authorization_endpoint=meta.get("authorization_endpoint", ""))
