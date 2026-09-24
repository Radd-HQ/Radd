import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.apitypes import TOTAL_COUNT_HEADER
from radd.kernel import capabilities as kcaps
from radd.modules.auth import authz
from radd.modules.auth.principals import ANYONE_ID, SIGNED_IN_ID
from radd.modules.auth.types import Permission
from radd.modules.auth.deps import Actor, CurrentUser

from . import service, directory
from .schemas import (
    BlockerRead,
    ProjectContentRead,
    InstanceConfigRead,
    InstanceStatusRead,
    ProjectCreate,
    ProjectRead,
    ProjectSummaryRead,
    ProjectUpdate,
    PublicAccessUpdate,
)

project_router = APIRouter(prefix="/projects", tags=["projects"])
instance_router = APIRouter(tags=["instance"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _instance_work_week(session: AsyncSession) -> list[str]:
    """The instance-scope work week, resolved through the scalar cascade (spec 50:
    an instance override set in settings wins over the env default). Deferred import
    keeps the load-order edge one-way (settings depends on projects, not vice-versa)."""
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey

    value = await settings_service.resolve(session, SettingKey.WORK_WEEK_DAYS)
    return [part.strip().lower() for part in str(value).split(",") if part.strip()]


async def _instance_hours_per_day(session: AsyncSession) -> int:
    """The global '1d'==N-hours factor (spec 67 follow-up: instance-only scalar) —
    the SPA duration formatter consumes it. Same deferred-import idiom as above."""
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey

    return int(await settings_service.resolve(session, SettingKey.TIMELOG_HOURS_PER_DAY))


@instance_router.get("/instance", response_model=InstanceConfigRead)
async def instance_config(session: Session, user: Actor) -> InstanceConfigRead:
    """Safe instance-level config the frontend needs (spec 35): the work week +
    the timelog duration factors (spec 67 follow-up). The auth flags come from the
    kernel capability registry (chokepoint-2 inversion), not inlined settings."""
    caps = kcaps.capability_map()
    return InstanceConfigRead(
        work_week_days=await _instance_work_week(session),
        timelog_hours_per_day=await _instance_hours_per_day(session),
        timelog_days_per_week=settings.timelog_days_per_week,
        sso_enabled=caps.get("sso", {}).get("enabled", False),
        ldap_enabled=caps.get("ldap", {}).get("enabled", False),
        anyone_id=ANYONE_ID,
        signed_in_id=SIGNED_IN_ID,
    )


@instance_router.get("/instance/status", response_model=InstanceStatusRead)
async def instance_status(user: Actor) -> InstanceStatusRead:
    """Non-secret deploy status for the instance settings surface (spec 50) — admin only.

    Chokepoint-2 inversion (docs/plugin-platform.md §3): every flag is now read from
    the kernel capability registry — each plugin declares its own `CapabilitySpec`
    (`sso`, `ldap`, `ai`, `storage`, `mfa`, `smtp`, `workers`, and each connector) —
    instead of this endpoint inlining `bool(settings.*)`. `connectors` is derived
    generically from every capability in the `connector` category, so a new connector
    plugin appears here with zero edits."""
    from radd.exceptions import ForbiddenError

    if not authz.is_instance_admin(user):
        raise ForbiddenError("instance settings require an instance admin")
    caps = kcaps.capability_map()
    return InstanceStatusRead(
        sso_enabled=caps.get("sso", {}).get("enabled", False),
        ldap_enabled=caps.get("ldap", {}).get("enabled", False),
        ldap_bind_account=caps.get("ldap", {}).get("bind_account", False),
        smtp_configured=caps.get("smtp", {}).get("enabled", False),
        ai_provider=caps.get("ai", {}).get("provider", ""),
        attachment_storage=caps.get("storage", {}).get("backend", ""),
        workers_enabled=caps.get("workers", {}).get("enabled", False),
        connectors={
            key: cap["enabled"]
            for key, cap in caps.items()
            if cap.get("category") == "connector"
        },
    )


@instance_router.get("/instance/login-options", response_model=InstanceConfigRead)
async def login_options(session: Session) -> InstanceConfigRead:
    """UNAUTHENTICATED mirror of /instance for the login page (spec 40) — only
    flags that must be known before sign-in (the timelog factors are harmless
    non-secrets, included so the two endpoints share one shape). Auth flags from
    the capability registry (no session/settings inlining)."""
    caps = kcaps.capability_map()
    return InstanceConfigRead(
        work_week_days=await _instance_work_week(session),
        timelog_hours_per_day=await _instance_hours_per_day(session),
        timelog_days_per_week=settings.timelog_days_per_week,
        sso_enabled=caps.get("sso", {}).get("enabled", False),
        ldap_enabled=caps.get("ldap", {}).get("enabled", False),
    )


@project_router.post("", response_model=ProjectRead, status_code=201)
async def create_project(data: ProjectCreate, session: Session, user: CurrentUser) -> ProjectRead:
    await authz.require(session, user, authz.Permission.PROJECT_CREATE)
    project = await service.create_project(session, data, actor_id=user.id)
    permissions = await authz.effective_permissions(session, user, project=project)
    return directory.project_read(project, permissions)


@project_router.get("", response_model=list[ProjectRead])
async def list_projects(
    session: Session, user: Actor, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0, hide_related: bool = False,
    permission: Permission | None = None,
    ids: Annotated[list[uuid.UUID] | None, Query(max_length=200)] = None,
) -> list[ProjectRead]:
    rows, total = await directory.page(
        session, user, q=q, limit=limit, offset=offset, hide_related=hide_related, ids=ids, permission=permission,
    )
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@project_router.put("/{project_id}/public-access", response_model=ProjectRead)
async def set_public_access(
    project_id: uuid.UUID, data: PublicAccessUpdate, session: Session, user: CurrentUser
) -> ProjectRead:
    """Spec 121: the two switches, written as the grants they are — the Public
    role to Anyone, the Contributor role to Signed-in users. `project.manage`
    opens the screen; D14 still applies (a delegate cannot hand the world an
    atom they do not hold here), through the same coverage check every
    delegated grant passes."""
    # Deferred: auth loads after projects, so its modules are import-time cycles here.
    from radd.modules.auth import public_access, roles as auth_roles
    from radd.modules.auth.roles_router import ensure_delegated_role_coverage
    from radd.modules.auth.types import BuiltinRoleKey

    project = await service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.PROJECT_MANAGE, project=project)
    if not authz.is_instance_admin(user):
        for key in (BuiltinRoleKey.PUBLIC, BuiltinRoleKey.CONTRIBUTOR):
            role = await auth_roles.role_by_key(session, key.value)
            await ensure_delegated_role_coverage(session, user, role, project)
    await public_access.set_public_access(
        session, project, public=data.public, contributions=data.contributions, actor_id=user.id
    )
    permissions = await authz.effective_permissions(session, user, project=project)
    return await directory.project_read_with_access(session, project, permissions)


@project_router.get("/summary", response_model=ProjectSummaryRead)
async def project_summary(session: Session, user: Actor) -> ProjectSummaryRead:
    """Aggregate affordances are independent of the directory's current page."""
    return await directory.summary(session, user)


@project_router.get("/by-key/{key}", response_model=ProjectRead)
async def project_by_key(key: str, session: Session, user: Actor) -> ProjectRead:
    return await directory.by_identity(session, user, key=key)


@project_router.get("/{project_id}", response_model=ProjectRead)
async def project_by_id(project_id: uuid.UUID, session: Session, user: Actor) -> ProjectRead:
    return await directory.by_identity(session, user, identifier=project_id)


@project_router.get("/{project_id}/content", response_model=ProjectContentRead)
async def project_content(project_id: uuid.UUID, session: Session, user: CurrentUser) -> ProjectContentRead:
    """RADD-1174: what deleting this project would destroy, and what forbids it —
    the confirmation dialog's source, gated like the delete itself so the
    numbers are never shown to someone who cannot act on them."""
    project = await service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.PROJECT_DELETE)
    inspection = await service.inspect_project(session, project)
    return ProjectContentRead(
        counts=inspection.counts,
        blockers=[BlockerRead(**vars(blocker)) for blocker in inspection.blockers],
    )


@project_router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """RADD-1174: hard-delete the project and everything in it. `project.delete`
    is a GLOBAL atom on purpose — `PROJECT_PERMISSIONS` feeds the builtin
    project Manager role (was Admin), and a delegated project admin must not be able to
    destroy the project. A blocker (mail still routed here) is a 409 naming it."""
    project = await service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.PROJECT_DELETE)
    await service.delete_project(session, project, actor_id=user.id)


@project_router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID, data: ProjectUpdate, session: Session, user: CurrentUser
) -> ProjectRead:
    """RADD-1009: rename + describe. `project.manage` on THIS project; the key
    is not editable (see `ProjectUpdate`). Declared after `GET /{project_id}`
    on purpose: same shape, different method, so neither can shadow the other,
    and the literal siblings (`/summary`, `/by-key/…`) are GETs declared above."""
    project = await service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.PROJECT_MANAGE, project=project)
    await service.update_project(session, project, data, actor_id=user.id)
    permissions = await authz.effective_permissions(session, user, project=project)
    return await directory.project_read_with_access(session, project, permissions)
