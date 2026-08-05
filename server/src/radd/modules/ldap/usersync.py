"""Automatic directory USER sync (spec 85): search the cascade-resolved users
base and mirror it — PROVISION unknown users (the spec-84 in-app import path:
SSO-only `source=ldap` accounts + a default-workspace member seat), UPDATE
changed display names on ldap-source users, and — only when the
`ldap_user_sync_deactivate_missing` toggle is on — DEACTIVATE ldap-source users
that vanished from the directory (session-revoking, never local/oidc accounts).

Directory identity is the EMAIL (the enumeration's dedupe key), so a changed
mail attribute reads as leaver+joiner, not a rename — documented in the spec-85
as-built notes. One pass, two consumers: the `ldap-usersync` PeriodicLoop
(run_workers + bind account gated; the enable toggle is re-resolved per tick)
and the on-demand `POST /ldap/sync/users`. Runs are recorded in
`directory_sync_state` (kind=user_sync) for GET /ldap/sync-status."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import UserSource
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.worker import PeriodicLoop

from . import service, state
from .types import SyncKind

logger = logging.getLogger(__name__)


@dataclass
class UserSyncResult:
    """What one sync pass did — persisted verbatim as the state row's payload."""

    provisioned: int = 0
    updated: int = 0
    deactivated: int = 0
    errors: list[str] = field(default_factory=list)

    def payload(self) -> dict:
        return {
            "provisioned": self.provisioned,
            "updated": self.updated,
            "deactivated": self.deactivated,
            "errors": self.errors[: settings.ldap_max_recorded_errors],
        }


async def run_user_sync(
    session: AsyncSession, actor_id: uuid.UUID | None = None
) -> UserSyncResult:
    """One full pass (flush-only — the caller owns the commit). The directory
    search runs on the service account under the cascade-resolved users base;
    the deactivate-missing toggle is resolved here too, so an instance override
    applies to the very next run."""
    base = await service.resolved_user_base(session)
    directory_users = await asyncio.to_thread(
        service.search_directory_users, "", base, await service.resolved_exclude_disabled(session)
    )
    deactivate_missing = bool(
        await settings_service.resolve(session, SettingKey.LDAP_USER_SYNC_DEACTIVATE_MISSING)
    )
    result = UserSyncResult()
    by_email = {du.email: du for du in directory_users}
    known = await auth_service.users_by_emails(session, by_email.keys())

    for email, directory_user in by_email.items():
        try:
            user = known.get(email)
            if user is None:
                user, created = await service.find_or_create_user(session, directory_user)
                if created:
                    # Spec 86: a new active user holds the global member floor
                    # automatically — no membership row to seed.
                    result.provisioned += 1
            elif (
                user.source == UserSource.LDAP
                and directory_user.name
                and directory_user.name != user.name
            ):
                # Matching is BY EMAIL — only the display name can drift in place.
                user.name = directory_user.name
                result.updated += 1
        except Exception as exc:
            logger.exception("ldap usersync: syncing %s failed", email)
            result.errors.append(f"{email}: {exc}")

    if deactivate_missing:
        ldap_actives = (
            (
                await session.execute(
                    select(User).where(User.source == UserSource.LDAP.value, User.active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for user in ldap_actives:
            if user.email not in by_email:
                if await auth_service.deactivate_user(session, user, actor_id=actor_id):
                    result.deactivated += 1

    await session.flush()
    await state.record_run(session, SyncKind.USER_SYNC, result.payload())
    logger.info(
        "ldap usersync under %s: +%d provisioned, %d updated, %d deactivated, %d errors",
        base,
        result.provisioned,
        result.updated,
        result.deactivated,
        len(result.errors),
    )
    return result


# --- the periodic loop (spec 85 §2) -------------------------------------------


async def run_once() -> None:
    """One tick. The bind account and the `ldap_user_sync_enabled` cascade value
    are re-checked here, per tick — flipping the toggle on the Directory page
    arms/disarms the loop without a restart."""
    async with SessionLocal() as session:
        # RADD-846: the bind account may live in the DB now — resolve before
        # deciding the loop is dormant, so configuring it needs no restart.
        await service.refresh_conn(session)
        if not service.bind_account_enabled():
            return
        if not bool(await settings_service.resolve(session, SettingKey.LDAP_USER_SYNC_ENABLED)):
            return
        await run_user_sync(session)
        await session.commit()


_loop = PeriodicLoop(
    run_once,
    interval=lambda: settings.ldap_user_sync_seconds,
    name="ldap-usersync",
    # Web-only processes skip (spec 48 split). The bind check moved INSIDE
    # run_once (RADD-846): a gate reading the overlay here would never wake a
    # loop whose bind account arrived via the DB after boot.
    enabled=lambda: settings.run_workers,
    sleep_first=True,  # no burst at startup; "Sync now" covers immediacy
)

start = _loop.start
stop = _loop.stop
