"""Connection + repository CRUD, env seeding, and webhook connection resolution (spec 111).

The interesting function here is `resolve_for_payload`: which host signed this
body. Spec 47 had one secret and one answer. With rows, the payload names its
repository, so the answer is a lookup — with a fallback that keeps a hook working
before anyone records its repository.
"""

from radd.modules.vcs import setup as vcs_setup
import hashlib
import hmac
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.vcs import timemirror
from radd.modules.vcs.types import VcsProvider
from radd.snapshot import Snapshot

from .models import ForgejoConnection, ForgejoRepo
from .schemas import ConnectionCreate, ConnectionUpdate, RepoCreate, RepoUpdate
from .types import ForgejoEvent, ForgejoEntity

logger = logging.getLogger(__name__)


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time check of the hex HMAC-SHA256 the X-Forgejo-Signature /
    X-Gitea-Signature header carries against a shared secret."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


# --- connections ---


async def list_connections(session: AsyncSession) -> list[ForgejoConnection]:
    rows = await session.execute(select(ForgejoConnection).order_by(ForgejoConnection.name))
    return list(rows.scalars())


async def get_connection(session: AsyncSession, connection_id: uuid.UUID) -> ForgejoConnection:
    connection = await session.get(ForgejoConnection, connection_id)
    if connection is None:
        raise NotFoundError(ForgejoEntity.CONNECTION, connection_id)
    return connection


#: Never in an event payload — a diff records that a credential CHANGED, no value.
SECRET_FIELDS: tuple[str, ...] = ("api_token", "webhook_secret")


async def _emit_connection(
    session: AsyncSession,
    event_type: ForgejoEvent,
    connection: ForgejoConnection,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ForgejoEntity.CONNECTION,
        entity_id=connection.id,
        actor_id=actor_id,
        payload={"name": connection.name, "base_url": connection.base_url},
        changes=diff,
    )


async def _repo_snapshot(session: AsyncSession, repo: ForgejoRepo) -> dict:
    """What an auditor reads for a repo: the project's KEY, not its uuid."""
    ref = await projects_service.project_ref(session, repo.project_id) if repo.project_id else None
    return {
        "full_name": repo.full_name,
        "project": ref["key"] if ref else None,
        "default_branch": repo.default_branch,
        "time_category_id": str(repo.time_category_id) if repo.time_category_id else None,
        "mirror_time": repo.mirror_time,
        "move_on_merge": repo.move_on_merge,
        "publish_on_release": repo.publish_on_release,
        "enabled": repo.enabled, "link_all_projects": repo.link_all_projects,
    }


async def _emit_repo(
    session: AsyncSession,
    event_type: ForgejoEvent,
    repo: ForgejoRepo,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ForgejoEntity.REPO,
        entity_id=repo.id,
        actor_id=actor_id,
        payload={"full_name": repo.full_name, "connection_id": str(repo.connection_id)},
        subjects={"project": repo.project_id},
        changes=diff,
    )


async def create_connection(
    session: AsyncSession, data: ConnectionCreate, *, actor_id: uuid.UUID | None = None
) -> ForgejoConnection:
    existing = await session.execute(
        select(ForgejoConnection).where(ForgejoConnection.name == data.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(ForgejoEntity.CONNECTION, data.name)
    await vcs_setup.claim_seed(session, "forgejo")
    connection = ForgejoConnection(
        name=data.name,
        base_url=data.base_url.rstrip("/"),
        api_token=data.api_token,
        webhook_secret=data.webhook_secret,
        active=data.active,
        verify_ssl=data.verify_ssl,
    )
    await vcs_setup.require_distinct_secret(session, ForgejoConnection, connection)
    session.add(connection)
    await session.flush()
    await refresh_connection_snapshot(session)
    await _emit_connection(session, ForgejoEvent.CONNECTION_CREATED, connection, actor_id)
    return connection


async def update_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
    data: ConnectionUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> ForgejoConnection:
    connection = await get_connection(session, connection_id)
    before = changes.snapshot(connection, changes.column_fields(connection))
    if data.name is not None:
        connection.name = data.name
    if data.base_url is not None:
        connection.base_url = data.base_url.rstrip("/")
    # Empty string = keep the stored credential (the ai_providers convention): a
    # form that round-trips a redacted value must not blank the secret.
    if data.api_token:
        connection.api_token = data.api_token
    if data.webhook_secret:
        connection.webhook_secret = data.webhook_secret
    if data.active is not None:
        connection.active = data.active
    if data.verify_ssl is not None:
        connection.verify_ssl = data.verify_ssl
    await vcs_setup.require_distinct_secret(session, ForgejoConnection, connection)
    await session.flush()
    await refresh_connection_snapshot(session)
    await _emit_connection(
        session,
        ForgejoEvent.CONNECTION_UPDATED,
        connection,
        actor_id,
        changes.diff_object(connection, before, hidden=SECRET_FIELDS),
    )
    return connection


async def delete_connection(
    session: AsyncSession, connection_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> None:
    connection = await get_connection(session, connection_id)
    await _emit_connection(session, ForgejoEvent.CONNECTION_DELETED, connection, actor_id)
    # RADD-1258: the identity map and parked time entries keyed by this connection.
    await timemirror.forget_connection(
        session, provider=VcsProvider.FORGEJO, connection_id=connection.id
    )
    await session.delete(connection)
    await session.flush()
    await refresh_connection_snapshot(session)


async def repo_count(session: AsyncSession, connection_id: uuid.UUID) -> int:
    rows = await session.execute(
        select(func.count()).select_from(ForgejoRepo).where(ForgejoRepo.connection_id == connection_id)
    )
    return int(rows.scalar_one())


# --- repositories ---


async def list_repos(
    session: AsyncSession, connection_id: uuid.UUID | None = None
) -> list[ForgejoRepo]:
    query = select(ForgejoRepo).order_by(ForgejoRepo.full_name)
    if connection_id is not None:
        query = query.where(ForgejoRepo.connection_id == connection_id)
    return list((await session.execute(query)).scalars())


async def get_repo(session: AsyncSession, repo_id: uuid.UUID) -> ForgejoRepo:
    repo = await session.get(ForgejoRepo, repo_id)
    if repo is None:
        raise NotFoundError(ForgejoEntity.REPO, repo_id)
    return repo


async def find_repo(session: AsyncSession, full_name: str, connection_id: uuid.UUID | None = None) -> ForgejoRepo | None:
    """By `owner/repo`, case-insensitively — Forgejo treats names that way."""
    query = select(ForgejoRepo).where(func.lower(ForgejoRepo.full_name) == full_name.lower())
    if connection_id is not None:
        query = query.where(ForgejoRepo.connection_id == connection_id)
    return await session.scalar(query)



async def create_repo(
    session: AsyncSession, data: RepoCreate, *, actor_id: uuid.UUID | None = None
) -> ForgejoRepo:
    await get_connection(session, data.connection_id)  # 404s an unknown connection
    existing = await session.execute(
        select(ForgejoRepo).where(
            ForgejoRepo.connection_id == data.connection_id,
            func.lower(ForgejoRepo.full_name) == data.full_name.lower(),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(ForgejoEntity.REPO, data.full_name)
    repo = ForgejoRepo(
        connection_id=data.connection_id,
        full_name=data.full_name,
        project_id=data.project_id,
        default_branch=data.default_branch,
    )
    session.add(repo)
    await session.flush()
    await _emit_repo(session, ForgejoEvent.REPO_CREATED, repo, actor_id)
    return repo


async def update_repo(
    session: AsyncSession, repo_id: uuid.UUID, data: RepoUpdate, *, actor_id: uuid.UUID | None = None
) -> ForgejoRepo:
    repo = await get_repo(session, repo_id)
    before = await _repo_snapshot(session, repo)
    if "project_id" in data.model_fields_set:  # explicit null clears the mapping
        repo.project_id = data.project_id
    if data.default_branch is not None:
        repo.default_branch = data.default_branch
    if "time_category_id" in data.model_fields_set:  # explicit null = the default
        repo.time_category_id = data.time_category_id
    if data.mirror_time is not None:
        repo.mirror_time = data.mirror_time
    if data.move_on_merge is not None:
        repo.move_on_merge = data.move_on_merge
    if data.publish_on_release is not None:
        repo.publish_on_release = data.publish_on_release
    if data.enabled is not None:
        repo.enabled = data.enabled
    if data.link_all_projects is not None:
        repo.link_all_projects = data.link_all_projects
    await session.flush()
    diff = changes.diff(before, await _repo_snapshot(session, repo))
    await _emit_repo(session, ForgejoEvent.REPO_UPDATED, repo, actor_id, diff)
    return repo


async def delete_repo(
    session: AsyncSession, repo_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> None:
    repo = await get_repo(session, repo_id)
    await _emit_repo(session, ForgejoEvent.REPO_DELETED, repo, actor_id)
    await session.delete(repo)
    await session.flush()


# --- webhook routing ---


async def resolve_for_payload(
    session: AsyncSession, payload: dict, raw_body: bytes, signature: str
) -> tuple[ForgejoConnection, ForgejoRepo | None] | None:
    """Authenticate one active host, then require its repository to be enabled.

    Secrets shared by multiple hosts are ambiguous and therefore rejected.
    """
    full_name = str((payload.get("repository") or {}).get("full_name") or "").strip().strip("/")
    verified = [c for c in await list_connections(session) if c.active and verify_signature(raw_body, signature, c.webhook_secret)]
    if len(verified) != 1:
        return None  # shared secrets cannot identify a host unambiguously
    connection = verified[0]
    repo = await find_repo(session, full_name, connection.id) if full_name else None
    if full_name and (repo is None or not repo.enabled):
        return None
    return connection, repo


# --- capability snapshot ------------------------------------------------------

# CapabilitySpec.check is sync — the attachments default-host idiom (RADD-899):
# write-through on connection writes + TTL'd so extra web replicas converge. The
# env secret is SEED-ONLY (spec 111); the connector pill answers from the ROWS.


async def _load_active_count() -> int:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(func.count()).select_from(ForgejoConnection).where(ForgejoConnection.active)
        )
        return int(rows.scalar_one())


_active_snapshot: Snapshot[int] = Snapshot(
    "forgejo.active-connections", _load_active_count, initial=0
)


def active_connection_count() -> int:
    return _active_snapshot.get()


async def refresh_connection_snapshot(session: AsyncSession) -> None:
    rows = await session.execute(
        select(func.count()).select_from(ForgejoConnection).where(ForgejoConnection.active)
    )
    _active_snapshot.set(int(rows.scalar_one()))


# --- env seed (spec-101 rule: the env key seeds ONE row, once) ---


async def seed_from_env() -> None:
    """Turn spec 47's `RADD_FORGEJO_WEBHOOK_SECRET` into a connection row, ONCE,
    then warm the capability snapshot.

    Seeding runs only when the table is empty, so an admin who deletes or renames
    the seeded row never has it reappear. The base URL is unknown to the env
    config (spec 47 only ever needed the secret), so it is left blank for an
    admin to fill in — the row exists so that webhooks keep verifying across the
    upgrade.
    """
    secret = settings.forgejo_webhook_secret.strip()
    async with SessionLocal() as session:
        rows = await session.execute(select(func.count()).select_from(ForgejoConnection))
        empty = int(rows.scalar_one()) == 0
        claimed = await vcs_setup.claim_seed(session, "forgejo") if secret or not empty else False
        if secret and empty and claimed:
            session.add(
                ForgejoConnection(
                    name="Forgejo",
                    base_url=settings.forgejo_base_url.rstrip("/"),
                    webhook_secret=secret,
                    active=True,
                )
            )
            logger.info("forgejo: seeded one connection from RADD_FORGEJO_WEBHOOK_SECRET")
        await session.commit()
        await refresh_connection_snapshot(session)
