"""RADD-1124: one canonical external id per VCS ref, and one row per ref.

The Forgejo webhook wrote a commit as its bare SHA while the backfill and the
CI stamp used `commit:<repo>:<sha>`, so a backfill after a webhook duplicated
every commit and a workflow run never found the webhook's row. Three seams are
pinned here: the receiver (same push twice, then CI, on one row), the upsert
seam under the unique index (a lost race becomes an update), and the
migration's rewrite of the rows the old webhook left behind.
"""

import hashlib
import hmac
import importlib.util
import json
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.clock import utcnow
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth.models import User
from radd.modules.forgejo import service as forgejo_service
from radd.modules.forgejo.router import router as forgejo_router
from radd.modules.forgejo.schemas import ConnectionCreate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.vcs import service as vcs
from radd.modules.vcs.ids import commit_external_id
from radd.modules.vcs.models import ItemVcsLink
from radd.modules.vcs.types import VcsProvider, VcsRefType

REPO = "pipe/tools"
HOST = "https://forge.example.com"
SHA = "4b2b1cdeadbeef1122334455667788990011aabb"


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _item(db):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"VI{uuid.uuid4().hex[:4].upper()}", name="vcs ids")
    )
    owner = User(name="Owner", email=f"{uuid.uuid4()}@test.invalid", instance_role="admin")
    db.add(owner)
    await db.flush()
    return await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="linked"), actor=owner
    )


async def _links(db, item_id):
    rows = await db.execute(select(ItemVcsLink).where(ItemVcsLink.item_id == item_id))
    return list(rows.scalars())


def _app(db) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(ForbiddenError)
    async def forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    async def session_override():
        yield db

    app.dependency_overrides[get_session] = session_override
    app.include_router(forgejo_router, prefix=settings.api_prefix)
    return app


def _signed(body: dict, secret: str, kind: str) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    return raw, {
        "X-Forgejo-Signature": hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
        "X-Forgejo-Event": kind,
    }


async def test_receiver_writes_one_row_per_commit_and_ci_finds_it(db):
    """The same push delivered twice is one row, spelled the way the backfill
    and the CI stamp spell it — so the workflow run lands on the webhook's row."""
    item = await _item(db)
    secret = "s3cret"
    await forgejo_service.create_connection(
        db, ConnectionCreate(name=f"c-{uuid.uuid4().hex[:6]}", base_url=HOST, webhook_secret=secret)
    )
    push = {
        "ref": "refs/heads/main",
        "repository": {"full_name": REPO, "html_url": f"{HOST}/{REPO}"},
        "commits": [{"id": SHA, "message": f"[{item.key}] done", "url": f"{HOST}/{REPO}/commit/{SHA}"}],
    }
    run = {
        "repository": {"full_name": REPO},
        "workflow_run": {"head_sha": SHA, "conclusion": "success", "html_url": f"{HOST}/{REPO}/actions/runs/1"},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://t") as client:
        for _ in range(2):
            raw, headers = _signed(push, secret, "push")
            response = await client.post("/api/v1/integrations/forgejo", content=raw, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["linked"] == 1
        raw, headers = _signed(run, secret, "workflow_run")
        stamped = await client.post("/api/v1/integrations/forgejo", content=raw, headers=headers)
        assert stamped.status_code == 200 and stamped.json()["linked"] == 1

    (row,) = await _links(db, item.id)
    assert row.external_id == commit_external_id(REPO, SHA) == f"commit:{REPO}:{SHA}"
    assert row.ci_state == "success"


async def test_a_lost_insert_race_becomes_the_update(db, monkeypatch):
    """Two deliveries of one push miss the lookup together; the index refuses
    the second insert and the seam updates the winner instead of raising."""
    item = await _item(db)
    external_id = commit_external_id(REPO, SHA)
    kwargs = dict(provider=VcsProvider.FORGEJO, ref_type=VcsRefType.COMMIT, external_id=external_id, url="u")
    first = await vcs.upsert_vcs_link(db, item.id, title="first", **kwargs)

    real_find = vcs._find_link
    misses = iter([True])

    async def blind_once(session, item_id, provider, ext):
        # The first lookup does not see the winner's row — the race, modelled.
        if next(misses, False):
            return None
        return await real_find(session, item_id, provider, ext)

    monkeypatch.setattr(vcs, "_find_link", blind_once)
    second = await vcs.upsert_vcs_link(db, item.id, title="second", **kwargs)
    assert second.id == first.id and second.title == "second"
    assert len(await _links(db, item.id)) == 1


# --- the migration's rewrite of what the old webhook left behind --------------

_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "h1124vcsid_canonical_vcs_external_ids.py"


def _migration():
    spec = importlib.util.spec_from_file_location("h1124vcsid", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rewrite(db) -> None:
    migration = _migration()
    for statement in (migration.DROP_YOUNGER_TWIN, migration.REWRITE_BARE, migration.LOWERCASE_REPO):
        await db.execute(text(statement))


def _row(item_id, external_id: str, url: str) -> ItemVcsLink:
    return ItemVcsLink(
        item_id=item_id, ref_type="commit", provider="forgejo", title="t", url=url, external_id=external_id
    )


async def test_migration_rewrites_bare_shas_from_the_url_and_drops_the_younger_twin(db):
    item = await _item(db)
    other = "0" * 40
    bare = _row(item.id, SHA, f"{HOST}/{REPO}/commit/{SHA}")
    twin = _row(item.id, commit_external_id(REPO, SHA), f"{HOST}/{REPO}/commit/{SHA}")
    # The webhook wrote the bare row first; the backfill's twin came a day later.
    bare.created_at, twin.created_at = utcnow() - timedelta(days=1), utcnow()
    twin.ci_state = "success"
    db.add(bare)
    lone = _row(item.id, other, f"{HOST}/Pipe/Tools/commit/{other}")
    typed = _row(item.id, "branch:Pipe/Tools:main", f"{HOST}/{REPO}/src/branch/main")
    db.add_all([twin, lone, typed])
    await db.flush()
    bare_id = bare.id  # read before the SQL below invalidates the identity map

    await _rewrite(db)

    db.expire_all()
    rows = {row.external_id: row for row in await _links(db, item.id)}
    assert set(rows) == {
        commit_external_id(REPO, SHA),
        commit_external_id(REPO, other),  # the bare SHA took its repo from the URL, lowercased
        f"branch:{REPO}:main",  # an admin-typed mixed-case repo now matches what the connector writes
    }
    # The pair kept its OLDEST row — the bare one — now spelled canonically.
    assert rows[commit_external_id(REPO, SHA)].id == bare_id
