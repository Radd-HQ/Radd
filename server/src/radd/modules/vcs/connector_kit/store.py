"""A connector's connections and repositories (RADD-1435): CRUD, audit events, the
capability snapshot, env seeding and webhook resolution — one implementation, bound
to each connector's spec. A delivery must verify against exactly ONE active
connection, and a repository it names must be recorded on THAT connection and
enabled (spec 111): a second host's genuine secret never authorises writes against
the first host's repositories."""

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd import secretbox
from radd.clock import utcnow
from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import CapabilitySpec
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.snapshot import Snapshot

from .. import timemirror
from ..setup import claim_seed, require_distinct_secret
from ..types import ConnectorSetting
from . import backfill
from .schemas import ConnectionCreate, ConnectionUpdate, RepoCreate, RepoUpdate, connection_create_for
from .spec import ConnectorSpec

logger = logging.getLogger(__name__)

#: Never in an event payload — a diff records that a credential CHANGED, no value.
SECRET_FIELDS: tuple[str, ...] = ("api_token", "webhook_secret")


def normalize_path(full_name: str) -> str:
    """A repository path as stored and matched: no surrounding blanks or slashes."""
    return full_name.strip().strip("/")


class ConnectorStore:
    def __init__(self, spec: ConnectorSpec) -> None:
        self.spec = spec
        #: The POST body: the base URL defaults to the public host when there is one.
        self.connection_create = connection_create_for(spec.wording.title, spec.wording.default_base_url)
        self._active: Snapshot[int] = Snapshot(
            f"{spec.provider.value}.active-connections", self._load_active_count, initial=0
        )

    @property
    def _connection(self):
        return self.spec.connection_model

    @property
    def _repo(self):
        return self.spec.repo_model

    # --- connections ---

    async def list_connections(self, session: AsyncSession) -> list[Any]:
        rows = await session.execute(select(self._connection).order_by(self._connection.name))
        return list(rows.scalars())

    async def get_connection(self, session: AsyncSession, connection_id: uuid.UUID) -> Any:
        connection = await session.get(self._connection, connection_id)
        if connection is None:
            raise NotFoundError(self.spec.entities.CONNECTION, connection_id)
        return connection

    async def _emit_connection(self, session, event_type, connection, actor_id, diff=None) -> None:
        await events.emit(
            session,
            event_type=event_type,
            entity_type=self.spec.entities.CONNECTION,
            entity_id=connection.id,
            actor_id=actor_id,
            payload={"name": connection.name, "base_url": connection.base_url},
            changes=diff,
        )

    async def create_connection(
        self, session: AsyncSession, data: ConnectionCreate, *, actor_id: uuid.UUID | None = None
    ) -> Any:
        if await session.scalar(select(self._connection).where(self._connection.name == data.name)) is not None:
            raise ConflictError(self.spec.entities.CONNECTION, data.name)
        # A connection made by hand means the env seed must never add one later.
        await claim_seed(session, self.spec.provider.value)
        connection = self._connection(
            name=data.name,
            base_url=(data.base_url or self.spec.wording.default_base_url).rstrip("/"),
            api_token=secretbox.seal(data.api_token),
            webhook_secret=secretbox.seal(data.webhook_secret),
            active=data.active,
            verify_ssl=data.verify_ssl,
        )
        await require_distinct_secret(session, self._connection, connection)
        session.add(connection)
        await session.flush()
        await self.refresh_connection_snapshot(session)
        await self._emit_connection(session, self.spec.events.CONNECTION_CREATED, connection, actor_id)
        return connection

    async def update_connection(
        self, session: AsyncSession, connection_id: uuid.UUID, data: ConnectionUpdate, *,
        actor_id: uuid.UUID | None = None,
    ) -> Any:
        connection = await self.get_connection(session, connection_id)
        # Credentials stored before RADD-1446 take their encrypted form on this save —
        # before the snapshot, so the adoption itself is not recorded as a change.
        connection.api_token = secretbox.adopt(connection.api_token)
        connection.webhook_secret = secretbox.adopt(connection.webhook_secret)
        before = changes.snapshot(connection, changes.column_fields(connection))
        if data.name is not None:
            connection.name = data.name
        if data.base_url is not None:
            connection.base_url = data.base_url.rstrip("/")
        # `KEEP_SECRET` = keep the stored credential: a form round-tripping a redacted
        # value must not blank the secret (the ai_providers convention).
        for credential in SECRET_FIELDS:
            if not secretbox.keeps_secret(getattr(data, credential)):
                setattr(connection, credential, secretbox.seal(getattr(data, credential)))
        if data.active is not None:
            connection.active = data.active
        if data.verify_ssl is not None:
            connection.verify_ssl = data.verify_ssl
        await require_distinct_secret(session, self._connection, connection)
        await session.flush()
        await self.refresh_connection_snapshot(session)
        await self._emit_connection(
            session, self.spec.events.CONNECTION_UPDATED, connection, actor_id,
            changes.diff_object(connection, before, hidden=SECRET_FIELDS),
        )
        return connection

    async def delete_connection(
        self, session: AsyncSession, connection_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> None:
        connection = await self.get_connection(session, connection_id)
        await self._emit_connection(session, self.spec.events.CONNECTION_DELETED, connection, actor_id)
        # RADD-1258: the identity map and parked time entries keyed by this connection.
        await timemirror.forget_connection(session, provider=self.spec.provider, connection_id=connection.id)
        await session.delete(connection)
        await session.flush()
        await self.refresh_connection_snapshot(session)

    async def repo_count(self, session: AsyncSession, connection_id: uuid.UUID) -> int:
        query = select(func.count()).select_from(self._repo).where(self._repo.connection_id == connection_id)
        return int(await session.scalar(query) or 0)

    # --- repositories ---

    async def list_repos(self, session: AsyncSession, connection_id: uuid.UUID | None = None) -> list[Any]:
        query = select(self._repo).order_by(self._repo.full_name)
        if connection_id is not None:
            query = query.where(self._repo.connection_id == connection_id)
        return list((await session.execute(query)).scalars())

    async def get_repo(self, session: AsyncSession, repo_id: uuid.UUID) -> Any:
        repo = await session.get(self._repo, repo_id)
        if repo is None:
            raise NotFoundError(self.spec.entities.REPO, repo_id)
        return repo

    async def find_repo(
        self, session: AsyncSession, full_name: str, connection_id: uuid.UUID | None = None
    ) -> Any | None:
        """By path, case-insensitively — every host treats repository paths that way."""
        query = select(self._repo).where(func.lower(self._repo.full_name) == full_name.lower())
        if connection_id is not None:
            query = query.where(self._repo.connection_id == connection_id)
        return await session.scalar(query)

    async def _repo_snapshot(self, session: AsyncSession, repo: Any) -> dict:
        """What an auditor reads for a repository: the project's KEY, not its uuid."""
        ref = await projects_service.project_ref(session, repo.project_id) if repo.project_id else None
        return {
            "full_name": repo.full_name,
            "project": ref["key"] if ref else None,
            "default_branch": repo.default_branch,
            "time_category_id": str(repo.time_category_id) if repo.time_category_id else None,
            "mirror_time": repo.mirror_time,
            "move_on_merge": repo.move_on_merge,
            "publish_on_release": repo.publish_on_release,
            "enabled": repo.enabled,
            "link_all_projects": repo.link_all_projects,
        }

    async def _emit_repo(self, session, event_type, repo, actor_id, diff=None) -> None:
        await events.emit(
            session,
            event_type=event_type,
            entity_type=self.spec.entities.REPO,
            entity_id=repo.id,
            actor_id=actor_id,
            payload={"full_name": repo.full_name, "connection_id": str(repo.connection_id)},
            subjects={"project": repo.project_id},
            changes=diff,
        )

    async def create_repo(
        self, session: AsyncSession, data: RepoCreate, *, actor_id: uuid.UUID | None = None
    ) -> Any:
        await self.get_connection(session, data.connection_id)  # 404s an unknown connection
        full_name = normalize_path(data.full_name)
        if await self.find_repo(session, full_name, data.connection_id) is not None:
            raise ConflictError(self.spec.entities.REPO, data.full_name)
        repo = self._repo(
            connection_id=data.connection_id,
            full_name=full_name,
            project_id=data.project_id,
            default_branch=data.default_branch,
        )
        session.add(repo)
        await session.flush()
        await self._emit_repo(session, self.spec.events.REPO_CREATED, repo, actor_id)
        return repo

    async def update_repo(
        self, session: AsyncSession, repo_id: uuid.UUID, data: RepoUpdate, *, actor_id: uuid.UUID | None = None
    ) -> Any:
        repo = await self.get_repo(session, repo_id)
        before = await self._repo_snapshot(session, repo)
        # Explicit null clears the mapping / returns to the default category.
        for nullable in ("project_id", "time_category_id"):
            if nullable in data.model_fields_set:
                setattr(repo, nullable, getattr(data, nullable))
        for field in ("default_branch", "mirror_time", "move_on_merge", "publish_on_release", "enabled", "link_all_projects"):
            if (value := getattr(data, field)) is not None:
                setattr(repo, field, value)
        await session.flush()
        diff = changes.diff(before, await self._repo_snapshot(session, repo))
        await self._emit_repo(session, self.spec.events.REPO_UPDATED, repo, actor_id, diff)
        return repo

    async def delete_repo(self, session: AsyncSession, repo_id: uuid.UUID, *, actor_id: uuid.UUID | None = None) -> None:
        repo = await self.get_repo(session, repo_id)
        await self._emit_repo(session, self.spec.events.REPO_DELETED, repo, actor_id)
        await session.delete(repo)
        await session.flush()

    async def backfill(
        self, session: AsyncSession, connection: Any, repo: Any, *,
        max_commits: int | None = None, transport: httpx.AsyncBaseTransport | None = None,
    ) -> backfill.BackfillReport:
        """Walk the repository's history and link what the webhook never saw."""
        report = await backfill.run(
            self.spec, session, connection, repo, max_commits=max_commits, transport=transport
        )
        repo.last_backfill_at = utcnow()
        await session.flush()
        return report

    # --- webhook routing ---

    async def resolve_for_payload(
        self, session: AsyncSession, payload: dict, raw_body: bytes, credential: str
    ) -> tuple[Any, Any | None] | None:
        """The one active connection this delivery authenticates against, and the
        enabled repository it names on THAT connection (None when it names none).
        A secret shared by several active hosts identifies none of them. The
        connector's `authenticate` compares constant-time against the DECRYPTED
        secret (RADD-1446) — the one place a webhook secret is decrypted."""
        full_name = normalize_path(self.spec.repo_name(payload))
        verified = [
            connection for connection in await self.list_connections(session)
            if connection.active
            and self.spec.authenticate(raw_body, credential, secretbox.decrypt(connection.webhook_secret))
        ]
        if len(verified) != 1:
            return None
        connection = verified[0]
        repo = await self.find_repo(session, full_name, connection.id) if full_name else None
        if full_name and (repo is None or not repo.enabled):
            return None
        return connection, repo

    # --- the capability snapshot (the RADD-899 idiom: CapabilitySpec.check is sync) ---

    async def _count_active(self, session: AsyncSession) -> int:
        query = select(func.count()).select_from(self._connection).where(self._connection.active)
        return int(await session.scalar(query) or 0)

    async def _load_active_count(self) -> int:
        async with SessionLocal() as session:
            return await self._count_active(session)

    def active_connection_count(self) -> int:
        return self._active.get()

    async def refresh_connection_snapshot(self, session: AsyncSession) -> None:
        self._active.set(await self._count_active(session))

    def capability(self) -> CapabilitySpec:
        """The connector pill: ACTIVE rows, since the env secret only seeds (spec 111)."""
        return CapabilitySpec(
            self.spec.provider.value,
            f"{self.spec.wording.title} connector",
            "connector",
            check=lambda: {"enabled": self.active_connection_count() > 0},
        )

    # --- startup ---

    async def encrypt_plaintext_credentials(self) -> None:
        """Credentials saved before RADD-1446 take their encrypted form. A missing
        secretbox key logs and skips — boot never waits on it."""
        try:
            async with SessionLocal() as session:
                for connection in await self.list_connections(session):
                    connection.api_token = secretbox.adopt(connection.api_token)
                    connection.webhook_secret = secretbox.adopt(connection.webhook_secret)
                await session.commit()
        except secretbox.SecretBoxError as exc:
            logger.warning(
                "%s: connection credentials stay plaintext this boot: %s", self.spec.provider.value, exc
            )

    # --- env seed (the spec-101 rule: the env key seeds ONE row, once) ---

    async def seed_from_env(self) -> None:
        """Seed one connection (+ one repository) from `RADD_<PROVIDER>_*` once,
        then warm the capability snapshot. A claimed seed never re-seeds, so a
        connection the admin deleted stays deleted."""
        spec = self.spec
        secret = str(spec.setting(ConnectorSetting.WEBHOOK_SECRET)).strip()
        async with SessionLocal() as session:
            empty = await session.scalar(select(func.count()).select_from(self._connection)) == 0
            claimed = await claim_seed(session, spec.provider.value) if secret or not empty else False
            if secret and empty and claimed:
                connection = self._connection(
                    name=spec.wording.title,
                    base_url=(str(spec.setting(ConnectorSetting.BASE_URL)) or spec.wording.default_base_url).rstrip("/"),
                    api_token=secretbox.seal(str(spec.setting(ConnectorSetting.API_TOKEN)).strip()),
                    webhook_secret=secretbox.seal(secret),
                    active=True,
                )
                session.add(connection)
                await session.flush()
                repo_name = normalize_path(str(spec.setting(ConnectorSetting.REPO)))
                if repo_name:
                    session.add(self._repo(connection_id=connection.id, full_name=repo_name))
                logger.info("%s: seeded one connection from the environment", spec.provider.value)
            await session.commit()
            await self.refresh_connection_snapshot(session)
