from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.kernel import capabilities as kcaps
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import InstanceConfigRead, InstanceStatusRead, ProjectCreate, ProjectRead

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
async def instance_config(session: Session, user: CurrentUser) -> InstanceConfigRead:
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
    )


@instance_router.get("/instance/status", response_model=InstanceStatusRead)
async def instance_status(user: CurrentUser) -> InstanceStatusRead:
    """Non-secret deploy status for the instance settings surface (spec 50) — admin only.

    Chokepoint-2 inversion (docs/plugin-platform.md §3): every flag is now read from
    the kernel capability registry — each plugin declares its own `CapabilitySpec`
    (`sso`, `ldap`, `ai`, `storage`, `mfa`, `smtp`, `workers`, and each connector) —
    instead of this endpoint inlining `bool(settings.*)`. `connectors` is derived
    generically from every capability in the `connector` category, so a new connector
    plugin appears here with zero edits."""
    from radd.exceptions import ForbiddenError
    from radd.modules.auth.types import InstanceRole

    if InstanceRole(user.instance_role) is not InstanceRole.ADMIN:
        raise ForbiddenError("instance settings require an instance admin")
    caps = kcaps.capability_map()
    return InstanceStatusRead(
        sso_enabled=caps.get("sso", {}).get("enabled", False),
        ldap_enabled=caps.get("ldap", {}).get("enabled", False),
        ldap_bind_account=caps.get("ldap", {}).get("bind_account", False),
        smtp_configured=caps.get("smtp", {}).get("enabled", False),
        mfa_available=caps.get("mfa", {}).get("enabled", False),
        ai_provider=caps.get("ai", {}).get("provider", ""),
        attachment_storage=caps.get("storage", {}).get("backend", settings.attachment_storage),
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


def _project_read(project: object, permissions: frozenset) -> ProjectRead:
    """Hydrate the CURRENT user's effective permissions onto the read model."""
    read = ProjectRead.model_validate(project)
    return read.model_copy(update={"permissions": sorted(permissions)})


@project_router.post("", response_model=ProjectRead, status_code=201)
async def create_project(data: ProjectCreate, session: Session, user: CurrentUser) -> ProjectRead:
    await authz.require(session, user, authz.Permission.PROJECT_CREATE)
    project = await service.create_project(session, data, actor_id=user.id)
    permissions = await authz.effective_permissions(session, user, project=project)
    return _project_read(project, permissions)


@project_router.get("", response_model=list[ProjectRead])
async def list_projects(session: Session, user: CurrentUser) -> list[ProjectRead]:
    await authz.require(session, user, authz.Permission.ITEM_READ)
    projects = await service.list_projects(session)
    permissions = await authz.permissions_for_projects(session, user, projects)
    return [_project_read(p, permissions[p.id]) for p in projects]
