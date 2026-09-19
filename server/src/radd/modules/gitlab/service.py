"""Connection + project CRUD, env seeding, and webhook connection resolution (RADD-1253).

`resolve_for_payload` decides which host sent a body: a recorded project names
its connection and only that connection's token is compared, so two hosts with
different secrets are unambiguous; an unrecorded project falls back to every
active connection so a hook registered before its project row still works.

GitLab does not sign bodies. It sends the hook's "Secret token" back verbatim in
`X-Gitlab-Token`, so verification is a constant-time string comparison.
"""

import hmac
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.vcs import timemirror
from radd.modules.vcs.types import VcsProvider
from radd.snapshot import Snapshot

from .models import GitlabConnection, GitlabRepo
from .schemas import ConnectionCreate, ConnectionUpdate, RepoCreate, RepoUpdate
from .types import GITLAB_COM, GitlabEntity, GitlabEvent

logger = logging.getLogger(__name__)


def verify_token(provided: str, secret: str) -> bool:
    """Constant-time check of the `X-Gitlab-Token` header against a hook secret.
    An empty secret verifies nothing — a connection with no secret is not a
    connection that accepts every body."""
    if not secret or not provided:
        return False
    return hmac.compare_digest(provided.strip(), secret)


# --- connections ---


async def list_connections(session: AsyncSession) -> list[GitlabConnection]:
    rows = await session.execute(select(GitlabConnection).order_by(GitlabConnection.name))
    return list(rows.scalars())


async def get_connection(session: AsyncSession, connection_id: uuid.UUID) -> GitlabConnection:
    connection = await session.get(GitlabConnection, connection_id)
    if connection is None:
        raise NotFoundError(GitlabEntity.CONNECTION, connection_id)
    return connection


#: Never in an event payload — a diff records that a credential CHANGED, no value.
SECRET_FIELDS: tuple[str, ...] = ("api_token", "webhook_secret")


async def _emit_connection(
    session: AsyncSession,
    event_type: GitlabEvent,
    connection: GitlabConnection,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=GitlabEntity.CONNECTION,
        entity_id=connection.id,
        actor_id=actor_id,
        payload={"name": connection.name, "base_url": connection.base_url},
        changes=diff,
    )


async def _repo_snapshot(session: AsyncSession, repo: GitlabRepo) -> dict:
    ref = await projects_service.project_ref(session, repo.project_id) if repo.project_id else None
    return {
        "full_name": repo.full_name,
        "project": ref["key"] if ref else None,
        "default_branch": repo.default_branch,
        "time_category_id": str(repo.time_category_id) if repo.time_category_id else None,
    }


async def _emit_repo(
    session: AsyncSession,
    event_type: GitlabEvent,
    repo: GitlabRepo,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=GitlabEntity.REPO,
        entity_id=repo.id,
        actor_id=actor_id,
        payload={"full_name": repo.full_name, "connection_id": str(repo.connection_id)},
        subjects={"project": repo.project_id},
        changes=diff,
    )


async def create_connection(
    session: AsyncSession, data: ConnectionCreate, *, actor_id: uuid.UUID | None = None
) -> GitlabConnection:
    existing = await session.execute(
        select(GitlabConnection).where(GitlabConnection.name == data.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(GitlabEntity.CONNECTION, data.name)
    connection = GitlabConnection(
        name=data.name,
        base_url=(data.base_url or GITLAB_COM).rstrip("/"),
        api_token=data.api_token,
        webhook_secret=data.webhook_secret,
        active=data.active,
        verify_ssl=data.verify_ssl,
    )
    session.add(connection)
    await session.flush()
    await refresh_connection_snapshot(session)
    await _emit_connection(session, GitlabEvent.CONNECTION_CREATED, connection, actor_id)
    return connection


async def update_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
    data: ConnectionUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> GitlabConnection:
    connection = await get_connection(session, connection_id)
    before = changes.snapshot(connection, changes.column_fields(connection))
    if data.name is not None:
        connection.name = data.name
    if data.base_url is not None:
        connection.base_url = data.base_url.rstrip("/")
    # Empty string = keep the stored credential (the ai_providers convention).
    if data.api_token:
        connection.api_token = data.api_token
    if data.webhook_secret:
        connection.webhook_secret = data.webhook_secret
    if data.active is not None:
        connection.active = data.active
    if data.verify_ssl is not None:
        connection.verify_ssl = data.verify_ssl
    await session.flush()
    await refresh_connection_snapshot(session)
    await _emit_connection(
        session,
        GitlabEvent.CONNECTION_UPDATED,
        connection,
        actor_id,
        changes.diff_object(connection, before, hidden=SECRET_FIELDS),
    )
    return connection


async def delete_connection(
    session: AsyncSession, connection_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> None:
    connection = await get_connection(session, connection_id)
    await _emit_connection(session, GitlabEvent.CONNECTION_DELETED, connection, actor_id)
    # RADD-1258: the identity map and parked time entries keyed by this connection.
    await timemirror.forget_connection(
        session, provider=VcsProvider.GITLAB, connection_id=connection.id
    )
    await session.delete(connection)
    await session.flush()
    await refresh_connection_snapshot(session)


async def repo_count(session: AsyncSession, connection_id: uuid.UUID) -> int:
    rows = await session.execute(
        select(func.count()).select_from(GitlabRepo).where(GitlabRepo.connection_id == connection_id)
    )
    return int(rows.scalar_one())


# --- projects (repositories) ---


async def list_repos(
    session: AsyncSession, connection_id: uuid.UUID | None = None
) -> list[GitlabRepo]:
    query = select(GitlabRepo).order_by(GitlabRepo.full_name)
    if connection_id is not None:
        query = query.where(GitlabRepo.connection_id == connection_id)
    return list((await session.execute(query)).scalars())


async def get_repo(session: AsyncSession, repo_id: uuid.UUID) -> GitlabRepo:
    repo = await session.get(GitlabRepo, repo_id)
    if repo is None:
        raise NotFoundError(GitlabEntity.REPO, repo_id)
    return repo


async def find_repo(session: AsyncSession, full_name: str) -> GitlabRepo | None:
    """By `path_with_namespace`, case-insensitively — GitLab paths are."""
    rows = await session.execute(
        select(GitlabRepo).where(func.lower(GitlabRepo.full_name) == full_name.strip("/").lower())
    )
    return rows.scalars().first()


async def create_repo(
    session: AsyncSession, data: RepoCreate, *, actor_id: uuid.UUID | None = None
) -> GitlabRepo:
    await get_connection(session, data.connection_id)  # 404s an unknown connection
    full_name = data.full_name.strip().strip("/")
    existing = await session.execute(
        select(GitlabRepo).where(
            GitlabRepo.connection_id == data.connection_id,
            func.lower(GitlabRepo.full_name) == full_name.lower(),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(GitlabEntity.REPO, data.full_name)
    repo = GitlabRepo(
        connection_id=data.connection_id,
        full_name=full_name,
        project_id=data.project_id,
        default_branch=data.default_branch,
    )
    session.add(repo)
    await session.flush()
    await _emit_repo(session, GitlabEvent.REPO_CREATED, repo, actor_id)
    return repo


async def update_repo(
    session: AsyncSession, repo_id: uuid.UUID, data: RepoUpdate, *, actor_id: uuid.UUID | None = None
) -> GitlabRepo:
    repo = await get_repo(session, repo_id)
    before = await _repo_snapshot(session, repo)
    if "project_id" in data.model_fields_set:  # explicit null clears the mapping
        repo.project_id = data.project_id
    if data.default_branch is not None:
        repo.default_branch = data.default_branch
    if "time_category_id" in data.model_fields_set:  # explicit null = the default
        repo.time_category_id = data.time_category_id
    await session.flush()
    diff = changes.diff(before, await _repo_snapshot(session, repo))
    await _emit_repo(session, GitlabEvent.REPO_UPDATED, repo, actor_id, diff)
    return repo


async def delete_repo(
    session: AsyncSession, repo_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> None:
    repo = await get_repo(session, repo_id)
    await _emit_repo(session, GitlabEvent.REPO_DELETED, repo, actor_id)
    await session.delete(repo)
    await session.flush()


# --- webhook routing ---


def payload_project_path(payload: dict) -> str:
    project = payload.get("project") or {}
    return str(project.get("path_with_namespace") or "").strip().strip("/")


async def resolve_for_payload(
    session: AsyncSession, payload: dict, token: str
) -> tuple[GitlabConnection, GitlabRepo | None] | None:
    """The connection whose hook secret this body carried, and the project row if
    we know it.

    A recorded project is verified against its OWN connection and nothing else —
    a second host's genuine secret must not authorise writes against the first
    host's projects. An unrecorded project falls back to every ACTIVE
    connection. None = nothing verified, which the router turns into 403.
    """
    full_name = payload_project_path(payload)
    if full_name:
        repo = await find_repo(session, full_name)
        if repo is not None:
            connection = await session.get(GitlabConnection, repo.connection_id)
            if connection is None or not connection.active:
                return None
            if verify_token(token, connection.webhook_secret):
                return connection, repo
            return None

    for connection in await list_connections(session):
        if connection.active and verify_token(token, connection.webhook_secret):
            return connection, None
    return None


# --- capability snapshot (RADD-899 idiom) ---


async def _load_active_count() -> int:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(func.count()).select_from(GitlabConnection).where(GitlabConnection.active)
        )
        return int(rows.scalar_one())


_active_snapshot: Snapshot[int] = Snapshot(
    "gitlab.active-connections", _load_active_count, initial=0
)


def active_connection_count() -> int:
    return _active_snapshot.get()


async def refresh_connection_snapshot(session: AsyncSession) -> None:
    rows = await session.execute(
        select(func.count()).select_from(GitlabConnection).where(GitlabConnection.active)
    )
    _active_snapshot.set(int(rows.scalar_one()))


# --- env seed (the spec-101 rule: the env key seeds ONE row, once) ---


async def seed_from_env() -> None:
    """Turn `RADD_GITLAB_WEBHOOK_SECRET` (+ optional `RADD_GITLAB_BASE_URL`,
    `RADD_GITLAB_API_TOKEN`, `RADD_GITLAB_REPO`) into a connection row ONCE,
    when the table is empty, then warm the capability snapshot. An admin who
    deletes the seeded row never has it reappear — and an instance that ran
    spec 31 from the environment keeps verifying its hook across the upgrade."""
    secret = settings.gitlab_webhook_secret.strip()
    async with SessionLocal() as session:
        rows = await session.execute(select(func.count()).select_from(GitlabConnection))
        if secret and int(rows.scalar_one()) == 0:
            connection = GitlabConnection(
                name="GitLab",
                base_url=(settings.gitlab_base_url or GITLAB_COM).rstrip("/"),
                api_token=settings.gitlab_api_token.strip(),
                webhook_secret=secret,
                active=True,
            )
            session.add(connection)
            await session.flush()
            repo_name = settings.gitlab_repo.strip().strip("/")
            if repo_name:
                session.add(GitlabRepo(connection_id=connection.id, full_name=repo_name))
            await session.commit()
            logger.info("gitlab: seeded one connection from RADD_GITLAB_WEBHOOK_SECRET")
        await refresh_connection_snapshot(session)
